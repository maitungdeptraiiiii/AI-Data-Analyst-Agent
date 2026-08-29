import json
from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from analyst_agent.errors import classify_sql_error
from analyst_agent.llm import create_chat_model
from analyst_agent.schemas import SQLFixOutput, SQLGenerationOutput
from analyst_agent.serialization import extract_metrics
from analyst_agent.state import ToolAgentState
from analyst_agent.tools.sql_tool import execute_readonly_sql

GENERATE_SYSTEM_PROMPT = (
    "Write exactly one read-only PostgreSQL SELECT or WITH query using supplied metadata."
)
REPAIR_SYSTEM_PROMPT = "Repair failed read-only SQL analysis. Preserve purpose and policy."


def generate(state: ToolAgentState) -> dict[str, object]:
    task = state["task"]
    metadata = json.dumps(task["dataset_summary"], default=str)
    if task["previous_code"] is not None:
        model = create_chat_model("executor").with_structured_output(SQLFixOutput)
        fixed = model.invoke(
            [
                ("system", REPAIR_SYSTEM_PROMPT),
                (
                    "human",
                    f"Step: {task['instruction']}\nPurpose: {task['previous_purpose']}\n"
                    f"Failed code:\n{task['previous_code']}\nError: {task['previous_error']}\n"
                    f"Metadata: {metadata}",
                ),
            ]
        )
        assert isinstance(fixed, SQLFixOutput)
        return {"generated_code": fixed.sql, "purpose": task["previous_purpose"]}

    model = create_chat_model("executor").with_structured_output(SQLGenerationOutput)
    generated = model.invoke(
        [
            ("system", GENERATE_SYSTEM_PROMPT),
            ("human", f"Step: {task['instruction']}\nMetadata: {metadata}"),
        ]
    )
    assert isinstance(generated, SQLGenerationOutput)
    return {"generated_code": generated.sql, "purpose": generated.purpose}


def run(state: ToolAgentState) -> dict[str, object]:
    code = state["generated_code"]
    assert code is not None
    try:
        rows = execute_readonly_sql(code)
        result: dict[str, object] = {
            "success": True,
            "rows": rows,
            "metrics": extract_metrics(rows),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - classified and re-typed below
        result = {"success": False, "rows": [], "metrics": {}, "error": classify_sql_error(exc)}
    return {"result": result}


def build_sql_agent_graph() -> Any:
    builder = StateGraph(ToolAgentState)
    builder.add_node("generate", generate)
    builder.add_node("run", run)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "run")
    builder.add_edge("run", END)
    return builder.compile()


@lru_cache
def get_sql_agent_graph() -> Any:
    return build_sql_agent_graph()
