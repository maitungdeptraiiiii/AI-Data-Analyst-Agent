from analyst_agent.config import get_settings
from analyst_agent.state import AgentState

PYTHON_HINTS = {
    "correlation",
    "regression",
    "forecast",
    "decomposition",
    "outlier",
    "anomaly",
    "statistical test",
    "rolling",
}


def choose_tool(state: AgentState) -> dict[str, object]:
    instruction = state["plan"][state["current_step"]].lower()
    dataset = state["dataset_info"]
    use_python = bool(
        dataset
        and dataset["n_rows"] <= get_settings().python_max_dataset_rows
        and any(hint in instruction for hint in PYTHON_HINTS)
    )
    return {"current_tool": "python" if use_python else "sql"}
