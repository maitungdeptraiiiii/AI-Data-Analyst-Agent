import argparse
from pathlib import Path
from typing import Literal, TypedDict, cast
from uuid import uuid4

from langgraph.types import Command

from analyst_agent.graph import get_runtime_graph
from analyst_agent.state import AgentState


class RunResult(TypedDict):
    status: Literal["completed", "interrupted"]
    thread_id: str
    final_answer: str | None
    interrupt_payload: object | None


def initial_state(question: str, dataset_path: str) -> AgentState:
    return {
        "messages": [],
        "run_id": uuid4().hex,
        "question": question,
        "dataset_path": dataset_path,
        "planner_status": None,
        "planner_message": None,
        "clarification_question": None,
        "clarification_history": [],
        "clarification_count": 0,
        "max_clarifications": 3,
        "dataset_info": None,
        "plan": [],
        "current_step": 0,
        "execution_max_retries": 2,
        "critic_verdict": None,
        "critic_reason": None,
        "critic_missing": [],
        "critic_retry_count": 0,
        "critic_max_retries": 2,
        "critic_history": [],
        "analysis_warnings": [],
        "analysis_log": [],
        "chart_plan": None,
        "charts": [],
        "chart_warning": None,
        "final_report": None,
        "draft_report": None,
        "grounding_violations": [],
        "grounding_retry_count": 0,
        "grounding_max_retries": 2,
        "grounding_status": None,
        "final_answer": None,
    }


def normalize_graph_result(result: dict[str, object], thread_id: str) -> RunResult:
    interrupts = result.get("__interrupt__")
    if isinstance(interrupts, list | tuple) and interrupts:
        first = interrupts[0]
        payload = getattr(first, "value", first)
        return {
            "status": "interrupted",
            "thread_id": thread_id,
            "final_answer": None,
            "interrupt_payload": payload,
        }
    return {
        "status": "completed",
        "thread_id": thread_id,
        "final_answer": cast(str | None, result.get("final_answer")),
        "interrupt_payload": None,
    }


def start_analysis(question: str, dataset_path: str, thread_id: str | None = None) -> RunResult:
    path = Path(dataset_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {path}")
    selected_thread_id = thread_id or str(uuid4())
    config = {"configurable": {"thread_id": selected_thread_id}}
    graph = get_runtime_graph().graph
    raw = graph.invoke(initial_state(question, str(path)), config=config)
    return normalize_graph_result(cast(dict[str, object], raw), selected_thread_id)


def resume_analysis(thread_id: str, answer: str) -> RunResult:
    if not answer.strip():
        raise ValueError("Clarification answer cannot be empty")
    config = {"configurable": {"thread_id": thread_id}}
    graph = get_runtime_graph().graph
    raw = graph.invoke(Command(resume=answer.strip()), config=config)
    return normalize_graph_result(cast(dict[str, object], raw), thread_id)


def _print_result(result: RunResult) -> None:
    if result["status"] == "completed":
        print(result["final_answer"] or "No report was generated.")
        return
    payload = result["interrupt_payload"]
    question = payload.get("question") if isinstance(payload, dict) else payload
    print("Analysis paused.")
    print(f"Thread ID: {result['thread_id']}")
    print(f"Question: {question}")
    print(f'\nResume with:\nanalyst-agent resume {result["thread_id"]} "your answer"')


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze CSV data with a LangGraph agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start a new analysis")
    start_parser.add_argument("dataset", help="Path to a CSV dataset")
    start_parser.add_argument("question", help="Analysis request")
    start_parser.add_argument("--thread-id", help="Optional stable checkpoint thread ID")

    resume_parser = subparsers.add_parser("resume", help="Resume a paused analysis")
    resume_parser.add_argument("thread_id", help="Thread ID printed by the start/resume command")
    resume_parser.add_argument("answer", help="Answer to the clarification question")

    args = parser.parse_args()
    if args.command == "start":
        _print_result(start_analysis(args.question, args.dataset, args.thread_id))
    else:
        _print_result(resume_analysis(args.thread_id, args.answer))


if __name__ == "__main__":
    main()
