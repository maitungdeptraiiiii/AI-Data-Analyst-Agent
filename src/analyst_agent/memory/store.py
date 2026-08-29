import json
import sqlite3
import time
from pathlib import Path

from analyst_agent.memory.schemas import AnalysisRecord

_DEFAULT_DB_PATH = Path("data/memory.sqlite")


class MemoryStore:
    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS past_analyses (
                    id TEXT PRIMARY KEY,
                    dataset_hash TEXT NOT NULL,
                    question TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    key_findings TEXT NOT NULL,
                    root_causes TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_past_dataset ON past_analyses(dataset_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_past_created ON past_analyses(created_at DESC)"
            )
            conn.commit()

    def save(self, record: AnalysisRecord) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO past_analyses
                (
                    id, dataset_hash, question, summary,
                    key_findings, root_causes, confidence, created_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.dataset_hash,
                    record.question,
                    record.summary,
                    json.dumps(record.key_findings, ensure_ascii=False),
                    json.dumps(record.root_causes, ensure_ascii=False),
                    record.confidence,
                    record.created_at,
                    json.dumps(record.metadata, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get_by_dataset(self, dataset_hash: str, limit: int = 5) -> list[AnalysisRecord]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    id, dataset_hash, question, summary,
                    key_findings, root_causes, confidence, created_at, metadata
                FROM past_analyses
                WHERE dataset_hash = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (dataset_hash, limit),
            )
            rows = cursor.fetchall()
            records: list[AnalysisRecord] = []
            for r in rows:
                records.append(
                    AnalysisRecord(
                        id=r[0],
                        dataset_hash=r[1],
                        question=r[2],
                        summary=r[3],
                        key_findings=json.loads(r[4]),
                        root_causes=json.loads(r[5]),
                        confidence=r[6],
                        created_at=r[7],
                        metadata=json.loads(r[8]),
                    )
                )
            return records

    def cleanup_expired(self, ttl_seconds: float = 90 * 86400.0) -> int:
        cutoff = time.time() - ttl_seconds
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM past_analyses WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount


_global_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _global_memory_store
    if _global_memory_store is None:
        _global_memory_store = MemoryStore()
    return _global_memory_store
