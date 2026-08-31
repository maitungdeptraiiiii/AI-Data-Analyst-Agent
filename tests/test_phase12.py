import time
from pathlib import Path

from analyst_agent.memory.retriever import compute_dataset_hash, format_memory_context
from analyst_agent.memory.schemas import AnalysisRecord
from analyst_agent.memory.store import MemoryStore
from analyst_agent.nodes.grounding_verifier import finalize_report
from analyst_agent.schemas import FinalReport


def test_memory_store_save_and_retrieve(tmp_path: Path) -> None:
    db_path = tmp_path / "memory_test.sqlite"
    store = MemoryStore(db_path)

    record = AnalysisRecord(
        id="run_1",
        dataset_hash="hash_abc123",
        question="Analyze sales",
        summary="Sales grew by 15%",
        key_findings=["Revenue up in North", "Laptops led the growth"],
        root_causes=["Supply chain improved"],
        confidence="high",
        created_at=time.time(),
    )
    store.save(record)

    fetched = store.get_by_dataset("hash_abc123")
    assert len(fetched) == 1
    assert fetched[0].id == "run_1"
    assert fetched[0].summary == "Sales grew by 15%"
    assert len(fetched[0].key_findings) == 2


def test_memory_store_cleanup_expired(tmp_path: Path) -> None:
    db_path = tmp_path / "memory_cleanup.sqlite"
    store = MemoryStore(db_path)

    old_record = AnalysisRecord(
        id="old_run",
        dataset_hash="hash_old",
        question="Old question",
        summary="Old summary",
        created_at=time.time() - 1000,
    )
    new_record = AnalysisRecord(
        id="new_run",
        dataset_hash="hash_new",
        question="New question",
        summary="New summary",
        created_at=time.time(),
    )
    store.save(old_record)
    store.save(new_record)

    deleted = store.cleanup_expired(ttl_seconds=500)
    assert deleted == 1

    remaining = store.get_by_dataset("hash_new")
    assert len(remaining) == 1
    assert remaining[0].id == "new_run"


def test_compute_dataset_hash() -> None:
    hash1 = compute_dataset_hash("data/sample_sales.csv")
    assert len(hash1) == 12

    # String fallback
    hash2 = compute_dataset_hash("non_existent_file.csv")
    assert len(hash2) == 12


def test_format_memory_context() -> None:
    records = [
        AnalysisRecord(
            id="r1",
            dataset_hash="h1",
            question="Why revenue dropped?",
            summary="Revenue dropped 20% due to discount reduction.",
            key_findings=["Phones decreased 10%"],
            created_at=time.time(),
        )
    ]
    formatted = format_memory_context(records)
    assert "Previous analyses on this dataset:" in formatted
    assert "Why revenue dropped?" in formatted
    assert "Phones decreased 10%" in formatted

    assert format_memory_context([]) == ""


def test_finalize_report_saves_memory(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "finalize_mem.sqlite"
    test_store = MemoryStore(db_path)
    monkeypatch.setattr("analyst_agent.memory.store.get_memory_store", lambda: test_store)

    report = FinalReport(
        summary="Final summary",
        key_findings=[],
        root_causes=[],
        recommendations=[],
        chart_paths=[],
        confidence="high",
        limitations=[],
    )

    state = {
        "run_id": "test_run_fin",
        "dataset_path": "data/sample_sales.csv",
        "question": "Sample analysis question",
        "draft_report": report.model_dump(),
        "final_report": None,
    }

    result = finalize_report(state)  # type: ignore[arg-type]
    assert result["final_report"] is not None

    hash_val = compute_dataset_hash("data/sample_sales.csv")
    saved = test_store.get_by_dataset(hash_val)
    assert len(saved) >= 1
    assert saved[0].id == "test_run_fin"
    assert saved[0].question == "Sample analysis question"
