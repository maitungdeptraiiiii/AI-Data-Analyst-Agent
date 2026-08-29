from typing import cast

import fakeredis
from test_phase8 import executor_agent_state, tool_task

from analyst_agent import streams
from analyst_agent.nodes import executor_agent
from analyst_agent.state import ToolResultData, ToolResultMessage
from analyst_agent.workers import tool_worker


class _FakeSettings:
    tool_agent_consumer_group = "tool-agents"
    tool_agent_visibility_timeout_ms = 0


def _fake_client() -> fakeredis.FakeStrictRedis:
    return fakeredis.FakeStrictRedis(decode_responses=True)


def _patch_bus(monkeypatch, client: fakeredis.FakeStrictRedis) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(streams, "get_redis_client", lambda: client)
    monkeypatch.setattr(streams, "get_settings", lambda: _FakeSettings())


def result_message(**updates: object) -> ToolResultMessage:
    message: ToolResultMessage = {
        "code": "SELECT SUM(revenue) FROM analysis.dataset_test",
        "purpose": "Calculate monthly revenue",
        "result": {
            "success": True,
            "rows": [{"sum": 100}],
            "metrics": {"sum": 100.0},
            "error": None,
        },
    }
    message.update(cast(dict, updates))
    return message


def test_publish_and_claim_tool_task_round_trips(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    task = tool_task()

    streams.publish_tool_task("sql", task)
    claimed = streams.claim_new_tasks("sql", consumer="worker-1", count=1, block_ms=100)

    assert len(claimed) == 1
    entry_id, claimed_task = claimed[0]
    assert claimed_task == task


def test_publish_and_await_tool_result_round_trips(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    message = result_message()

    streams.publish_tool_result("step_1:0", message)
    received = streams.await_tool_result("step_1:0", timeout_sec=1.0)

    assert received == message
    assert streams.result_already_published("step_1:0") is True


def test_await_tool_result_times_out_when_nothing_published(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    assert streams.await_tool_result("missing", timeout_sec=0.2) is None


def test_ensure_consumer_group_is_idempotent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    client = streams.get_redis_client()
    streams.ensure_consumer_group(client, "tasks:sql")
    streams.ensure_consumer_group(client, "tasks:sql")  # must not raise BUSYGROUP


def test_reclaim_stuck_tasks_picks_up_unacked_entries(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    task = tool_task()
    streams.publish_tool_task("sql", task)
    # worker-1 claims it but crashes before XACK
    streams.claim_new_tasks("sql", consumer="worker-1", count=1, block_ms=100)

    reclaimed = streams.reclaim_stuck_tasks("sql", consumer="worker-2", count=10)

    assert len(reclaimed) == 1
    assert reclaimed[0][1] == task


def test_ack_task_removes_it_from_the_pending_list(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    streams.publish_tool_task("sql", tool_task())
    claimed = streams.claim_new_tasks("sql", consumer="worker-1", count=1, block_ms=100)
    entry_id, _task = claimed[0]

    streams.ack_task("sql", entry_id)

    assert streams.reclaim_stuck_tasks("sql", consumer="worker-2", count=10) == []


class _FakeToolAgentGraph:
    def __init__(self, code: str, purpose: str, result: ToolResultData) -> None:
        self.code, self.purpose, self.result = code, purpose, result
        self.calls = 0

    def invoke(self, initial: object) -> dict[str, object]:
        self.calls += 1
        return {"generated_code": self.code, "purpose": self.purpose, "result": self.result}


def test_worker_processes_task_and_publishes_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    fake_graph = _FakeToolAgentGraph(
        code="SELECT SUM(revenue) FROM analysis.dataset_test",
        purpose="Calculate monthly revenue",
        result={"success": True, "rows": [{"sum": 100}], "metrics": {"sum": 100.0}, "error": None},
    )
    monkeypatch.setitem(tool_worker._TOOL_AGENT_GRAPHS, "sql", lambda: fake_graph)
    task = tool_task()

    tool_worker.process_task("sql", task)

    message = streams.await_tool_result(task["correlation_id"], timeout_sec=1.0)
    assert message is not None
    assert message["code"] == fake_graph.code
    assert message["result"]["success"] is True
    assert fake_graph.calls == 1


def test_worker_skips_reprocessing_an_already_published_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    fake_graph = _FakeToolAgentGraph(
        code="SELECT 1",
        purpose="p",
        result={"success": True, "rows": [], "metrics": {}, "error": None},
    )
    monkeypatch.setitem(tool_worker._TOOL_AGENT_GRAPHS, "sql", lambda: fake_graph)
    task = tool_task()

    tool_worker.process_task("sql", task)
    tool_worker.process_task("sql", task)  # redelivered (e.g. after XAUTOCLAIM)

    assert fake_graph.calls == 1


def test_run_once_reclaims_then_claims_and_acks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    empty_result: ToolResultData = {"success": True, "rows": [], "metrics": {}, "error": None}
    fake_graph = _FakeToolAgentGraph(code="SELECT 1", purpose="p", result=empty_result)
    monkeypatch.setitem(tool_worker._TOOL_AGENT_GRAPHS, "sql", lambda: fake_graph)
    streams.publish_tool_task("sql", tool_task())

    handled = tool_worker.run_once("sql", consumer="worker-1", count=1, block_ms=100)

    assert handled == 1
    assert fake_graph.calls == 1
    assert streams.reclaim_stuck_tasks("sql", consumer="worker-2", count=10) == []


def test_dispatch_tool_round_trips_through_redis_and_worker(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    fake_graph = _FakeToolAgentGraph(
        code="SELECT SUM(revenue) FROM analysis.dataset_test",
        purpose="Calculate monthly revenue",
        result={"success": True, "rows": [{"sum": 100}], "metrics": {"sum": 100.0}, "error": None},
    )
    monkeypatch.setitem(tool_worker._TOOL_AGENT_GRAPHS, "sql", lambda: fake_graph)

    original_publish = streams.publish_tool_task

    def publish_then_run_worker(tool, task):  # type: ignore[no-untyped-def]
        original_publish(tool, task)
        tool_worker.run_once(tool, consumer="worker-1", count=1, block_ms=100)

    monkeypatch.setattr(streams, "publish_tool_task", publish_then_run_worker)

    state = executor_agent_state(wait_timeout_sec=2.0)
    update = executor_agent.dispatch_tool(state)

    assert fake_graph.calls == 1
    assert update["code"] == fake_graph.code
    result = cast(ToolResultData, update["tool_result"])
    assert result["success"] is True
    attempts = cast(list, update["attempts"])
    assert attempts[0]["success"] is True


def test_dispatch_tool_times_out_when_no_worker_responds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_bus(monkeypatch, _fake_client())
    state = executor_agent_state(wait_timeout_sec=0.2)

    update = executor_agent.dispatch_tool(state)

    result = cast(ToolResultData, update["tool_result"])
    assert result["success"] is False
    assert result["error"] is not None
    assert result["error"]["category"] == "infrastructure"
    assert result["error"]["retryable"] is True
    executor_state = executor_agent_state(
        tool_result=result, local_retry_count=0, local_max_retries=2
    )
    assert executor_agent.route_after_dispatch(executor_state) == "retry"
