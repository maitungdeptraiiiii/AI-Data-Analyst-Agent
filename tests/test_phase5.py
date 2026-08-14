import sqlite3
from pathlib import Path
from typing import Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from analyst_agent.checkpointing import create_checkpointer
from analyst_agent.cli import initial_state, normalize_graph_result
from analyst_agent.graph import route_after_planner
from analyst_agent.nodes.ask_user import ask_user
from analyst_agent.state import AgentState


def build_clarification_test_graph(checkpointer):  # type: ignore[no-untyped-def]
    def scripted_planner(state: AgentState) -> dict[str, object]:
        count = state["clarification_count"]
        if count < 2:
            return {
                "planner_status": "need_clarification",
                "clarification_question": f"Clarification question {count + 1}?",
                "plan": [],
            }
        return {
            "planner_status": "ready",
            "clarification_question": None,
            "plan": ["Analyze clarified request"],
        }

    def route(state: AgentState) -> Literal["clarify", "finish"]:
        return "clarify" if state["planner_status"] == "need_clarification" else "finish"

    def finish(state: AgentState) -> dict[str, object]:
        return {"final_answer": f"Completed after {state['clarification_count']} answers"}

    builder = StateGraph(AgentState)
    builder.add_node("planner", scripted_planner)
    builder.add_node("ask_user", ask_user)
    builder.add_node("finish", finish)
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route, {"clarify": "ask_user", "finish": "finish"})
    builder.add_edge("ask_user", "planner")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


def test_two_consecutive_clarifications_pause_and_resume() -> None:
    graph = build_clarification_test_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "two-rounds"}}

    first_raw = graph.invoke(initial_state("Ambiguous request", "data/sample_sales.csv"), config)
    first = normalize_graph_result(first_raw, "two-rounds")
    assert first["status"] == "interrupted"
    assert first["interrupt_payload"]["round"] == 1  # type: ignore[index]

    second_raw = graph.invoke(Command(resume="Answer one"), config)
    second = normalize_graph_result(second_raw, "two-rounds")
    assert second["status"] == "interrupted"
    assert second["interrupt_payload"]["round"] == 2  # type: ignore[index]

    final_raw = graph.invoke(Command(resume="Answer two"), config)
    final = normalize_graph_result(final_raw, "two-rounds")
    assert final["status"] == "completed"
    assert final["final_answer"] == "Completed after 2 answers"
    state = graph.get_state(config).values
    assert state["clarification_count"] == 2
    assert state["clarification_history"] == [
        {"question": "Clarification question 1?", "answer": "Answer one"},
        {"question": "Clarification question 2?", "answer": "Answer two"},
    ]


def test_sqlite_saver_setup_and_resume_from_new_graph_instance(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    saver_a, connection_a = create_checkpointer(database_path)
    graph_a = build_clarification_test_graph(saver_a)
    config = {"configurable": {"thread_id": "persistent"}}
    first = graph_a.invoke(initial_state("Ambiguous", "data/sample_sales.csv"), config)
    assert "__interrupt__" in first
    connection_a.close()

    saver_b, connection_b = create_checkpointer(database_path)
    try:
        graph_b = build_clarification_test_graph(saver_b)
        second = graph_b.invoke(Command(resume="Persisted answer"), config)
        normalized = normalize_graph_result(second, "persistent")
        assert normalized["status"] == "interrupted"
        assert normalized["interrupt_payload"]["round"] == 2  # type: ignore[index]
    finally:
        connection_b.close()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"checkpoints", "writes"}.issubset(tables)


def test_clarification_cap_routes_to_bailout() -> None:
    state = initial_state("Ambiguous", "data/sample_sales.csv")
    state.update(
        planner_status="need_clarification",
        clarification_question="Still ambiguous?",
        clarification_count=3,
        max_clarifications=3,
    )
    assert route_after_planner(state) == "clarification_bailout"
