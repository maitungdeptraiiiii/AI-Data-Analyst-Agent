import json

from analyst_agent.context import format_clarification_context
from analyst_agent.errors import classify_sql_error
from analyst_agent.llm import create_chat_model
from analyst_agent.sandbox import execute_python_sandbox
from analyst_agent.schemas import PythonGenerationOutput, SQLGenerationOutput
from analyst_agent.serialization import extract_metrics
from analyst_agent.state import AgentState, AnalysisAttempt, AnalysisStep
from analyst_agent.tools.sql_tool import execute_readonly_sql


def _generate(state: AgentState, instruction: str) -> tuple[str, str]:
    tool = state["current_tool"]
    schema = PythonGenerationOutput if tool == "python" else SQLGenerationOutput
    system = (
        "Write a Python script for a sandbox that ALREADY provides these names in scope — "
        "do not import or redefine them, just use them directly: "
        "`load_dataset()` (call it with no arguments to get the dataset as a pandas DataFrame; "
        "this is a local helper, NOT the Hugging Face `datasets` library — never write "
        "`import datasets` or `from datasets import ...`), `pd` (pandas), `np` (numpy). "
        "The only import statements allowed at all are `import pandas as pd`, `import numpy as "
        "np`, `import math`, `import statistics`, `import datetime` — and none of those are "
        "needed since pd/np are already provided. "
        "End the script by assigning exactly two variables: `metrics` (a dict of str -> "
        "int/float) and `result` (a pandas DataFrame or a list of dicts). "
        "No filesystem, network, process, SQL, or chart operations."
        if tool == "python"
        else "Write exactly one read-only PostgreSQL SELECT or WITH query using supplied metadata."
    )
    model = create_chat_model("executor").with_structured_output(schema)
    clarification = format_clarification_context(state["clarification_history"])
    generated = model.invoke(
        [
            ("system", system),
            (
                "human",
                f"Request: {state['question']}\n{clarification}\n"
                f"Step: {instruction}\nMetadata: {json.dumps(state['dataset_info'], default=str)}",
            ),
        ]
    )
    if isinstance(generated, PythonGenerationOutput):
        return generated.code, generated.purpose
    assert isinstance(generated, SQLGenerationOutput)
    return generated.sql, generated.purpose


def execute_step(state: AgentState) -> dict[str, object]:
    instruction = state["plan"][state["current_step"]]
    tool = state["current_tool"] or "sql"
    code, purpose = state["current_code"], state["current_purpose"]
    if code is None:
        code, purpose = _generate(state, instruction)
    rows: list[dict[str, object]] = []
    metrics: dict[str, float] = {}
    error = None
    if tool == "python":
        dataset = state["dataset_info"]
        assert dataset is not None
        result = execute_python_sandbox(code, dataset["table_name"])
        rows, metrics, error = result["rows"], result["metrics"], result["error"]
    else:
        try:
            rows = execute_readonly_sql(code)
            metrics = extract_metrics(rows)
        except Exception as exc:
            error = classify_sql_error(exc)
    attempt: AnalysisAttempt = {
        "attempt": len(state["current_attempts"]) + 1,
        "tool": tool,
        "code": code,
        "success": error is None,
        "error_category": error["category"] if error else None,
        "error_code": error["code"] if error else None,
        "error_message": error["message"] if error else None,
    }
    return {
        "current_code": code,
        "current_purpose": purpose,
        "current_rows": rows,
        "current_metrics": metrics,
        "current_error": error,
        "current_attempts": [*state["current_attempts"], attempt],
    }


def finalize_step(state: AgentState) -> dict[str, object]:
    code, tool = state["current_code"], state["current_tool"]
    if code is None or tool is None:
        raise ValueError("Cannot finalize without tool code")
    error = state["current_error"]
    step: AnalysisStep = {
        "step_id": f"step_{len(state['analysis_log']) + 1}",
        "instruction": state["plan"][state["current_step"]],
        "tool": tool,
        "code": code,
        "rows": state["current_rows"],
        "metrics": state["current_metrics"],
        "success": error is None,
        "error": error["message"] if error else None,
        "attempts": state["current_attempts"],
    }
    return {
        "analysis_log": [*state["analysis_log"], step],
        "current_step": state["current_step"] + 1,
        "current_tool": None,
        "current_code": None,
        "current_purpose": None,
        "current_rows": [],
        "current_metrics": {},
        "current_error": None,
        "current_attempts": [],
        "execution_retry_count": 0,
    }
