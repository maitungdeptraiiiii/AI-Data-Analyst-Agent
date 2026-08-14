import json

from analyst_agent.context import format_clarification_context
from analyst_agent.llm import create_chat_model
from analyst_agent.schemas import PythonFixOutput, SQLFixOutput
from analyst_agent.state import AgentState


def fix_and_retry(state: AgentState) -> dict[str, object]:
    error, code, tool = state["current_error"], state["current_code"], state["current_tool"]
    if error is None or code is None or tool is None:
        raise ValueError("Fix node requires failed tool code")
    schema = PythonFixOutput if tool == "python" else SQLFixOutput
    model = create_chat_model("executor").with_structured_output(schema)
    clarification = format_clarification_context(state["clarification_history"])
    system = (
        "Repair failed Python for a sandbox that ALREADY provides `load_dataset()` (call with no "
        "arguments for a pandas DataFrame; a local helper, NOT the Hugging Face `datasets` "
        "library — never import `datasets`), `pd`, and `np` in scope. Only "
        "`import pandas as pd` / `import numpy as np` / `import math` / `import statistics` / "
        "`import datetime` are allowed, and none are needed for the already-provided names. "
        "End by assigning `metrics` (dict of str -> int/float) and `result` "
        "(DataFrame or list of dicts). Preserve the original purpose."
        if tool == "python"
        else "Repair failed read-only SQL analysis. Preserve purpose and policy."
    )
    fixed = model.invoke(
        [
            ("system", system),
            (
                "human",
                f"Request: {state['question']}\n{clarification}\n"
                f"Purpose: {state['current_purpose']}\nFailed code:\n{code}\n"
                f"Error: {error['message']}\n"
                f"Metadata: {json.dumps(state['dataset_info'], default=str)}",
            ),
        ]
    )
    if isinstance(fixed, PythonFixOutput):
        new_code = fixed.code
    else:
        assert isinstance(fixed, SQLFixOutput)
        new_code = fixed.sql
    return {
        "current_code": new_code,
        "current_error": None,
        "current_rows": [],
        "current_metrics": {},
        "execution_retry_count": state["execution_retry_count"] + 1,
    }
