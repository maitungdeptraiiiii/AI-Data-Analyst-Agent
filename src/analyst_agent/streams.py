"""Redis Streams bus for the Executor Agent <-> Tool Agent boundary (mục 6.3.4b).

This is the only ranh giới in the graph that crosses a process boundary: the Executor Agent
(in-process with the Orchestrator) publishes a `ToolTask` onto `tasks:{tool}` and blocks on
`results:{correlation_id}`; a Tool Agent worker (`analyst_agent.workers.tool_worker`), running
as its own process/pool, consumes `tasks:{tool}` through a consumer group and publishes the
`ToolResultMessage` back.
"""

import json
import time
from functools import lru_cache
from typing import Any, cast

import redis

from analyst_agent.config import get_settings
from analyst_agent.state import ToolName, ToolResultMessage, ToolTaskData

_RESULT_TTL_SECONDS = 3600


@lru_cache
def get_redis_client() -> redis.Redis:
    # socket_timeout=None: reads must stay unbounded because XREAD/XREADGROUP calls below pass
    # their own server-side BLOCK duration — a finite client-side timeout races against it and
    # raises a spurious redis.exceptions.TimeoutError whenever the server legitimately blocks
    # for the full BLOCK window (e.g. no new tasks yet). socket_connect_timeout stays bounded so
    # an unreachable Redis host still fails fast instead of hanging forever.
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_timeout=None,
        socket_connect_timeout=5,
    )


def task_stream(tool: ToolName) -> str:
    return f"tasks:{tool}"


def result_stream(correlation_id: str) -> str:
    return f"results:{correlation_id}"


def ensure_consumer_group(client: redis.Redis, stream: str) -> None:
    group = get_settings().tool_agent_consumer_group
    try:
        client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def publish_tool_task(tool: ToolName, task: ToolTaskData) -> None:
    client = get_redis_client()
    stream = task_stream(tool)
    ensure_consumer_group(client, stream)
    client.xadd(stream, {"payload": json.dumps(task)})


def await_tool_result(correlation_id: str, timeout_sec: float) -> ToolResultMessage | None:
    """Block on `results:{correlation_id}` until a Tool Agent worker publishes, or time out."""
    client = get_redis_client()
    stream = result_stream(correlation_id)
    deadline = time.monotonic() + timeout_sec
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        raw = client.xread({stream: "0"}, count=1, block=max(1, int(remaining * 1000)))
        response = cast(list[tuple[str, list[tuple[str, dict[str, str]]]]], raw)
        if response:
            _, entries = response[0]
            _entry_id, fields = entries[0]
            return cast(ToolResultMessage, json.loads(fields["payload"]))


def publish_tool_result(correlation_id: str, message: ToolResultMessage) -> None:
    client = get_redis_client()
    stream = result_stream(correlation_id)
    client.xadd(stream, {"payload": json.dumps(message)})
    client.expire(stream, _RESULT_TTL_SECONDS)


def result_already_published(correlation_id: str) -> bool:
    """Idempotency guard: at-least-once delivery can redeliver a task (XAUTOCLAIM after a
    stuck worker, or a crash after processing but before XACK) — a worker must skip
    reprocessing if it already published a result for this task."""
    return bool(get_redis_client().exists(result_stream(correlation_id)))


def claim_new_tasks(
    tool: ToolName, consumer: str, count: int, block_ms: int
) -> list[tuple[str, ToolTaskData]]:
    client = get_redis_client()
    stream = task_stream(tool)
    ensure_consumer_group(client, stream)
    group = get_settings().tool_agent_consumer_group
    response = client.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
    return _decode_entries(response)


def reclaim_stuck_tasks(
    tool: ToolName, consumer: str, count: int
) -> list[tuple[str, ToolTaskData]]:
    """Sweep tasks another consumer claimed but never XACKed within the visibility timeout —
    it likely crashed or hung (mục 6.3.4b's stuck-task reclaim)."""
    client = get_redis_client()
    stream = task_stream(tool)
    ensure_consumer_group(client, stream)
    group = get_settings().tool_agent_consumer_group
    min_idle_ms = get_settings().tool_agent_visibility_timeout_ms
    _cursor, claimed, _deleted = client.xautoclaim(
        stream, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=count
    )
    return _decode_entries([[stream, claimed]])


def ack_task(tool: ToolName, entry_id: str) -> None:
    client = get_redis_client()
    group = get_settings().tool_agent_consumer_group
    client.xack(task_stream(tool), group, entry_id)


def _decode_entries(response: Any) -> list[tuple[str, ToolTaskData]]:
    if not response:
        return []
    _stream, entries = response[0]
    return [(entry_id, json.loads(fields["payload"])) for entry_id, fields in entries]
