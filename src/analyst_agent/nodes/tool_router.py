from analyst_agent.config import get_settings
from analyst_agent.state import DatasetSummaryData, ToolName

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


def select_tool(instruction: str, dataset_summary: DatasetSummaryData) -> ToolName:
    use_python = bool(
        dataset_summary
        and dataset_summary["n_rows"] <= get_settings().python_max_dataset_rows
        and any(hint in instruction.lower() for hint in PYTHON_HINTS)
    )
    return "python" if use_python else "sql"
