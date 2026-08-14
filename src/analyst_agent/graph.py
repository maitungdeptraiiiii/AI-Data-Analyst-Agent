import atexit
from functools import lru_cache
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from analyst_agent.checkpointing import GraphRuntime, create_checkpointer
from analyst_agent.config import get_settings
from analyst_agent.nodes.ask_user import ask_user, bailout_clarification
from analyst_agent.nodes.chart_creator import create_chart_node
from analyst_agent.nodes.chart_planner import plan_chart
from analyst_agent.nodes.critic import bailout_after_critic, review_evidence
from analyst_agent.nodes.data_inspector import inspect_data
from analyst_agent.nodes.executor import execute_step, finalize_step
from analyst_agent.nodes.fix_and_retry import fix_and_retry
from analyst_agent.nodes.planner import create_plan
from analyst_agent.nodes.replan import create_additional_plan
from analyst_agent.nodes.reporter import create_report
from analyst_agent.nodes.tool_router import choose_tool
from analyst_agent.state import AgentState


def route_after_planner(
    state: AgentState,
) -> Literal["inspect", "clarify", "report", "clarification_bailout"]:
    if state["planner_status"] == "need_clarification":
        if state["clarification_count"] >= state["max_clarifications"]:
            return "clarification_bailout"
        return "clarify"
    if state["planner_status"] != "ready" or not state["plan"]:
        return "report"
    return "inspect"


def route_after_execution(state: AgentState) -> Literal["continue", "critic"]:
    if state["current_step"] < len(state["plan"]):
        return "continue"
    return "critic"


def route_after_sql(state: AgentState) -> Literal["retry", "finalize"]:
    error = state["current_error"]
    if (
        error is not None
        and error["retryable"]
        and state["execution_retry_count"] < state["execution_max_retries"]
    ):
        return "retry"
    return "finalize"


def route_after_critic(state: AgentState) -> Literal["replan", "charts", "bailout"]:
    if state["critic_verdict"] == "pass":
        return "charts"
    if state["critic_retry_count"] >= state["critic_max_retries"]:
        return "bailout"
    return "replan"


def route_after_replan(state: AgentState) -> Literal["execute", "report"]:
    return "execute" if state["plan"] else "report"


def route_after_chart_plan(state: AgentState) -> Literal["chart", "report"]:
    return "chart" if state["chart_plan"] is not None else "report"


def build_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    builder = StateGraph(AgentState)
    builder.add_node("planner", create_plan)
    builder.add_node("ask_user", ask_user)
    builder.add_node("clarification_bailout", bailout_clarification)
    builder.add_node("data_inspector", inspect_data)
    builder.add_node("executor", execute_step)
    builder.add_node("tool_router", choose_tool)
    builder.add_node("fix_and_retry", fix_and_retry)
    builder.add_node("finalize_step", finalize_step)
    builder.add_node("critic", review_evidence)
    builder.add_node("replan", create_additional_plan)
    builder.add_node("critic_bailout", bailout_after_critic)
    builder.add_node("chart_planner", plan_chart)
    builder.add_node("chart_creator", create_chart_node)
    builder.add_node("reporter", create_report)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "inspect": "data_inspector",
            "clarify": "ask_user",
            "report": "reporter",
            "clarification_bailout": "clarification_bailout",
        },
    )
    builder.add_edge("ask_user", "planner")
    builder.add_edge("clarification_bailout", "reporter")
    builder.add_edge("data_inspector", "tool_router")
    builder.add_edge("tool_router", "executor")
    builder.add_conditional_edges(
        "executor",
        route_after_sql,
        {"retry": "fix_and_retry", "finalize": "finalize_step"},
    )
    builder.add_edge("fix_and_retry", "executor")
    builder.add_conditional_edges(
        "finalize_step",
        route_after_execution,
        {"continue": "tool_router", "critic": "critic"},
    )
    builder.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "replan": "replan",
            "charts": "chart_planner",
            "bailout": "critic_bailout",
        },
    )
    builder.add_conditional_edges(
        "replan",
        route_after_replan,
        {"execute": "tool_router", "report": "reporter"},
    )
    builder.add_edge("critic_bailout", "reporter")
    builder.add_conditional_edges(
        "chart_planner",
        route_after_chart_plan,
        {"chart": "chart_creator", "report": "reporter"},
    )
    builder.add_edge("chart_creator", "reporter")
    builder.add_edge("reporter", END)
    return builder.compile(checkpointer=checkpointer)


@lru_cache
def get_runtime_graph() -> GraphRuntime:
    checkpointer, connection = create_checkpointer(get_settings().checkpoint_db_path)
    runtime = GraphRuntime(graph=build_graph(checkpointer), connection=connection)
    atexit.register(runtime.close)
    return runtime
