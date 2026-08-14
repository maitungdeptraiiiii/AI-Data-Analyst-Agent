from langgraph.types import interrupt

from analyst_agent.state import AgentState, ClarificationTurn


def ask_user(state: AgentState) -> dict[str, object]:
    question = state["clarification_question"]
    if not question:
        raise ValueError("Ask User requires a clarification question")

    answer = interrupt(
        {
            "type": "clarification",
            "question": question,
            "round": state["clarification_count"] + 1,
        }
    )
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Clarification response must be a non-empty string")
    turn: ClarificationTurn = {"question": question, "answer": answer.strip()}
    return {
        "clarification_history": [*state["clarification_history"], turn],
        "clarification_count": state["clarification_count"] + 1,
        "clarification_question": None,
        "planner_status": None,
        "planner_message": None,
        "plan": [],
        "current_step": 0,
    }


def bailout_clarification(state: AgentState) -> dict[str, object]:
    warning = (
        "Analysis could not start because required clarification remained unresolved after "
        f"{state['max_clarifications']} rounds."
    )
    if state["clarification_question"]:
        warning += f" Unresolved question: {state['clarification_question']}"
    return {
        "analysis_warnings": [*state["analysis_warnings"], warning],
        "planner_message": warning,
    }
