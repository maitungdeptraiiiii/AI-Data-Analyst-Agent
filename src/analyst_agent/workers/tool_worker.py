"""Tool Agent worker: a standalone process that consumes `tasks:{tool}` from Redis Streams,
runs the (in-process) Tool Agent subgraph, and publishes the result — mục 6.3.3/6.3.4b.

Run with: `python -m analyst_agent.workers.tool_worker sql`
"""

import argparse
import uuid

from analyst_agent import streams
from analyst_agent.nodes.tool_agents.python_agent import get_python_agent_graph
from analyst_agent.nodes.tool_agents.sql_agent import get_sql_agent_graph
from analyst_agent.state import ToolAgentState, ToolName, ToolResultMessage, ToolTaskData

_TOOL_AGENT_GRAPHS = {"sql": get_sql_agent_graph, "python": get_python_agent_graph}


def process_task(tool: ToolName, task: ToolTaskData) -> None:
    if streams.result_already_published(task["correlation_id"]):
        return
    initial: ToolAgentState = {
        "task": task,
        "generated_code": None,
        "purpose": None,
        "result": None,
    }
    tool_state = _TOOL_AGENT_GRAPHS[tool]().invoke(initial)
    result = tool_state["result"]
    assert result is not None
    message: ToolResultMessage = {
        "code": tool_state["generated_code"] or "",
        "purpose": tool_state["purpose"] or "",
        "result": result,
    }
    streams.publish_tool_result(task["correlation_id"], message)


def _process_and_ack(tool: ToolName, entry_id: str, task: ToolTaskData) -> bool:
    try:
        process_task(tool, task)
    except Exception:  # noqa: BLE001 - leave unacked so XAUTOCLAIM retries it elsewhere
        return False
    streams.ack_task(tool, entry_id)
    return True


def run_once(tool: ToolName, consumer: str, count: int = 1, block_ms: int = 5000) -> int:
    """Run one poll cycle: reclaim stuck tasks first, then read new ones. Returns tasks handled."""
    handled = 0
    for entry_id, task in streams.reclaim_stuck_tasks(tool, consumer, count):
        handled += _process_and_ack(tool, entry_id, task)
    for entry_id, task in streams.claim_new_tasks(tool, consumer, count, block_ms):
        handled += _process_and_ack(tool, entry_id, task)
    return handled


def run_worker(tool: ToolName, consumer: str | None = None) -> None:
    consumer = consumer or f"{tool}-{uuid.uuid4().hex[:8]}"
    while True:
        run_once(tool, consumer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Tool Agent worker over Redis Streams")
    parser.add_argument("tool", choices=["sql", "python"])
    parser.add_argument("--consumer", default=None, help="Consumer name (default: random)")
    args = parser.parse_args()
    run_worker(args.tool, args.consumer)


if __name__ == "__main__":
    main()
