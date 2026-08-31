import hashlib
from pathlib import Path

from analyst_agent.memory.schemas import AnalysisRecord
from analyst_agent.memory.store import get_memory_store


def compute_dataset_hash(dataset_path: str) -> str:
    path = Path(dataset_path)
    if not path.is_file():
        return hashlib.sha256(dataset_path.encode("utf-8")).hexdigest()[:12]
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def retrieve_relevant_memory(dataset_path: str) -> list[AnalysisRecord]:
    """Fetch previous analysis records for the given dataset."""
    dataset_hash = compute_dataset_hash(dataset_path)
    store = get_memory_store()
    return store.get_by_dataset(dataset_hash)


def format_memory_context(records: list[AnalysisRecord]) -> str:
    """Format past analyses into context for LLM prompts."""
    if not records:
        return ""

    entries: list[str] = []
    for r in records[:3]:
        findings_str = "; ".join(r.key_findings[:2]) if r.key_findings else "N/A"
        entries.append(
            f"- Question: '{r.question}'\n  Summary: {r.summary}\n  Key findings: {findings_str}"
        )
    return "Previous analyses on this dataset:\n" + "\n".join(entries)
