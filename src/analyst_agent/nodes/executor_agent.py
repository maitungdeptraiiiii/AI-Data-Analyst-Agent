from functools import lru_cache
from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph

from analyst_agent import streams
from analyst_agent.config import get_settings
from analyst_agent.nodes.tool_router import select_tool
from analyst_agent.state import (
    AgentState,
    AnalysisAttempt,
    AnalysisStep,
    DatasetSummaryData,
    ExecutorAgentState,
    ExecutorResultData,
    ExecutorTaskData,
    ToolResultData,
    ToolTaskData,
)


def route_tool(state: ExecutorAgentState) -> dict[str, object]:
    task = state["task"]
    return {"tool_choice": select_tool(task["instruction"], task["dataset_summary"])}


def dispatch_tool(state: ExecutorAgentState) -> dict[str, object]:
    """Publish a ToolTask onto `tasks:{tool}` and block for the ToolResult on
    `results:{correlation_id}` (mục 6.3.4b) — the only cross-process hop in the graph."""
    task = state["task"]
    tool_choice = state["tool_choice"]
    assert tool_choice is not None
    previous_error = state["tool_result"]["error"] if state["tool_result"] else None
    correlation_id = f"{task['step_id']}:{state['local_retry_count']}"
    tool_task: ToolTaskData = {
        "correlation_id": correlation_id,
        "instruction": task["instruction"],
        "dataset_summary": task["dataset_summary"],
        "attempt": state["local_retry_count"] + 1,
        "previous_code": state["code"],
        "previous_purpose": state["purpose"],
        "previous_error": previous_error["message"] if previous_error else None,
    }
    streams.publish_tool_task(tool_choice, tool_task)
    message = streams.await_tool_result(correlation_id, state["wait_timeout_sec"])
    if message is None:
        # Worker never answered within wait_timeout_sec — treat as a hung/crashed Tool
        # Agent (mục 6.3.2): a technical, retryable failure, not a code-quality one.
        code, purpose = state["code"] or "", state["purpose"]
        result: ToolResultData = {
            "success": False,
            "rows": [],
            "metrics": {},
            "error": {
                "category": "infrastructure",
                "code": None,
                "message": "Tool Agent worker did not respond within the wait timeout",
                "retryable": True,
            },
        }
    else:
        code, purpose, result = message["code"], message["purpose"], message["result"]
    attempt: AnalysisAttempt = {
        "attempt": tool_task["attempt"],
        "tool": tool_choice,
        "code": code,
        "success": result["error"] is None,
        "error_category": result["error"]["category"] if result["error"] else None,
        "error_code": result["error"]["code"] if result["error"] else None,
        "error_message": result["error"]["message"] if result["error"] else None,
    }
    return {
        "code": code,
        "purpose": purpose,
        "tool_result": result,
        "attempts": [*state["attempts"], attempt],
    }


def route_after_dispatch(state: ExecutorAgentState) -> Literal["retry", "finalize"]:
    result = state["tool_result"]
    assert result is not None
    error = result["error"]
    retries_left = state["local_retry_count"] < state["local_max_retries"]
    if error is not None and error["retryable"] and retries_left:
        return "retry"
    return "finalize"


def prepare_retry(state: ExecutorAgentState) -> dict[str, object]:
    return {"local_retry_count": state["local_retry_count"] + 1}


def finalize(state: ExecutorAgentState) -> dict[str, object]:
    result = state["tool_result"]
    assert result is not None and state["tool_choice"] is not None and state["code"] is not None
    executor_result: ExecutorResultData = {
        "step_id": state["task"]["step_id"],
        "success": result["error"] is None,
        "tool_used": state["tool_choice"],
        "code": state["code"],
        "purpose": state["purpose"] or "",
        "rows": result["rows"],
        "metrics": result["metrics"],
        "error": result["error"]["message"] if result["error"] else None,
        "attempts": state["attempts"],
    }
    return {"result": executor_result}


def build_executor_agent_graph() -> Any:
    builder = StateGraph(ExecutorAgentState)
    builder.add_node("route_tool", route_tool)
    builder.add_node("dispatch_tool", dispatch_tool)
    builder.add_node("prepare_retry", prepare_retry)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "route_tool")
    builder.add_edge("route_tool", "dispatch_tool")
    builder.add_conditional_edges(
        "dispatch_tool",
        route_after_dispatch,
        {"retry": "prepare_retry", "finalize": "finalize"},
    )
    builder.add_edge("prepare_retry", "dispatch_tool")
    builder.add_edge("finalize", END)
    return builder.compile()


@lru_cache
def get_executor_agent_graph() -> Any:
    return build_executor_agent_graph()


def _dataset_summary(state: AgentState) -> DatasetSummaryData:
    dataset = state["dataset_info"]
    assert dataset is not None
    return {
        "table_name": dataset["table_name"],
        "columns": dataset["columns"],
        "n_rows": dataset["n_rows"],
        "null_summary": dataset["null_summary"],
    }


def run_executor_agent(state: AgentState) -> dict[str, object]:
    """Orchestrator node: builds an ExecutorTask, runs the Executor Agent subgraph in-process
    (subgraph-as-node, mục 6.3.4a), and folds the returned ExecutorResult into analysis_log."""
    task: ExecutorTaskData = {
        "step_id": f"step_{len(state['analysis_log']) + 1}",
        "instruction": state["plan"][state["current_step"]],
        "dataset_summary": _dataset_summary(state),
    }
    initial: ExecutorAgentState = {
        "task": task,
        "tool_choice": None,
        "code": None,
        "purpose": None,
        "tool_result": None,
        "attempts": [],
        "local_retry_count": 0,
        "local_max_retries": state["execution_max_retries"],
        "wait_timeout_sec": get_settings().tool_agent_wait_timeout_seconds,
        "result": None,
    }
    final_state = cast(ExecutorAgentState, get_executor_agent_graph().invoke(initial))
    result = final_state["result"]
    assert result is not None
    step: AnalysisStep = {
        "step_id": result["step_id"],
        "instruction": task["instruction"],
        "tool": result["tool_used"],
        "code": result["code"],
        "rows": result["rows"],
        "metrics": result["metrics"],
        "success": result["success"],
        "error": result["error"],
        "attempts": result["attempts"],
    }
    return {
        "analysis_log": [*state["analysis_log"], step],
        "current_step": state["current_step"] + 1,
    }
