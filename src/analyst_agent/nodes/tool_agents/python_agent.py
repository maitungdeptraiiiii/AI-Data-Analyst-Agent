import json
from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from analyst_agent.llm import create_chat_model
from analyst_agent.sandbox import execute_python_sandbox
from analyst_agent.schemas import PythonFixOutput, PythonGenerationOutput
from analyst_agent.state import ToolAgentState

GENERATE_SYSTEM_PROMPT = (
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
)
REPAIR_SYSTEM_PROMPT = (
    "Repair failed Python for a sandbox that ALREADY provides `load_dataset()` (call with no "
    "arguments for a pandas DataFrame; a local helper, NOT the Hugging Face `datasets` "
    "library — never import `datasets`), `pd`, and `np` in scope. Only "
    "`import pandas as pd` / `import numpy as np` / `import math` / `import statistics` / "
    "`import datetime` are allowed, and none are needed for the already-provided names. "
    "End by assigning `metrics` (dict of str -> int/float) and `result` "
    "(DataFrame or list of dicts). Preserve the original purpose."
)


def generate(state: ToolAgentState) -> dict[str, object]:
    task = state["task"]
    metadata = json.dumps(task["dataset_summary"], default=str)
    if task["previous_code"] is not None:
        model = create_chat_model("executor").with_structured_output(PythonFixOutput)
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
        assert isinstance(fixed, PythonFixOutput)
        return {"generated_code": fixed.code, "purpose": task["previous_purpose"]}

    model = create_chat_model("executor").with_structured_output(PythonGenerationOutput)
    generated = model.invoke(
        [
            ("system", GENERATE_SYSTEM_PROMPT),
            ("human", f"Step: {task['instruction']}\nMetadata: {metadata}"),
        ]
    )
    assert isinstance(generated, PythonGenerationOutput)
    return {"generated_code": generated.code, "purpose": generated.purpose}


def run(state: ToolAgentState) -> dict[str, object]:
    code = state["generated_code"]
    assert code is not None
    table_name = state["task"]["dataset_summary"]["table_name"]
    result = execute_python_sandbox(code, table_name)
    return {"result": result}


def build_python_agent_graph() -> Any:
    builder = StateGraph(ToolAgentState)
    builder.add_node("generate", generate)
    builder.add_node("run", run)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "run")
    builder.add_edge("run", END)
    return builder.compile()


@lru_cache
def get_python_agent_graph() -> Any:
    return build_python_agent_graph()
