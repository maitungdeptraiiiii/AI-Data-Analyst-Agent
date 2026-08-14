from pathlib import Path

from analyst_agent.database import ingest_csv, inspect_dataset
from analyst_agent.state import AgentState


def inspect_data(state: AgentState) -> dict[str, object]:
    dataset_path = Path(state["dataset_path"]).expanduser().resolve()
    table_name = ingest_csv(dataset_path)
    return {"dataset_info": inspect_dataset(table_name)}

