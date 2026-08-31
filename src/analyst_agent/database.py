import atexit
import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg import Connection, sql
from psycopg_pool import ConnectionPool

from analyst_agent.config import get_settings
from analyst_agent.state import DatasetInfo

ANALYSIS_SCHEMA = "analysis"
_SAFE_COLUMN = re.compile(r"[^a-zA-Z0-9_]+")
_TEMPORAL_COLUMN = re.compile(
    r"(^|_)(date|datetime|timestamp|time|created_at|updated_at)($|_)", re.IGNORECASE
)
_ingest_pool: ConnectionPool[Connection[Any]] | None = None


def get_ingest_pool() -> ConnectionPool[Connection[Any]]:
    global _ingest_pool
    if _ingest_pool is None:
        _ingest_pool = ConnectionPool(
            conninfo=get_settings().postgres_ingest_dsn,
            min_size=1,
            max_size=4,
            open=True,
        )
        atexit.register(_ingest_pool.close)
    return _ingest_pool


get_ingest_pool()


@contextmanager
def ingest_connection() -> Iterator[Connection[Any]]:
    with get_ingest_pool().connection() as connection:
        yield connection


def dataset_table_name(csv_path: Path) -> str:
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()[:12]
    return f"dataset_{digest}"


def _normalize_column(name: object, position: int) -> str:
    normalized = _SAFE_COLUMN.sub("_", str(name).strip()).strip("_").lower()
    if not normalized:
        normalized = f"column_{position}"
    if normalized[0].isdigit():
        normalized = f"col_{normalized}"
    return normalized


def _unique_columns(columns: list[object]) -> list[str]:
    used: dict[str, int] = {}
    result: list[str] = []
    for position, column in enumerate(columns, start=1):
        base = _normalize_column(column, position)
        used[base] = used.get(base, 0) + 1
        result.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return result


def _postgres_type(dtype: Any) -> str:
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "DOUBLE PRECISION"
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMPTZ"
    return "TEXT"


def infer_temporal_columns(frame: pd.DataFrame, minimum_success_ratio: float = 0.9) -> pd.DataFrame:
    """Parse date-like columns when most non-null values are valid timestamps.

    Column names provide the first signal so identifiers, product codes, and other arbitrary text
    are not accidentally converted just because a few values happen to resemble dates.
    """
    converted = frame.copy()
    for column in converted.columns:
        series = converted[column]
        if not _TEMPORAL_COLUMN.search(str(column)) or not (
            pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype)
        ):
            continue

        non_null_count = int(series.notna().sum())
        if non_null_count == 0:
            continue
        parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
        success_ratio = float(parsed.notna().sum()) / non_null_count
        if success_ratio >= minimum_success_ratio:
            converted[column] = parsed
    return converted


def ingest_csv(csv_path: Path) -> str:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {csv_path}")
    if csv_path.suffix.lower() != ".csv":
        raise ValueError("Phase 1 only supports CSV datasets")

    frame = pd.read_csv(csv_path)
    if frame.columns.empty:
        raise ValueError("CSV must contain a header row")
    frame.columns = _unique_columns(list(frame.columns))
    frame = infer_temporal_columns(frame)
    table_name = dataset_table_name(csv_path)

    column_definitions = [
        sql.SQL("{} {}").format(sql.Identifier(str(column)), sql.SQL(_postgres_type(dtype)))
        for column, dtype in frame.dtypes.items()
    ]
    table_identifier = sql.Identifier(ANALYSIS_SCHEMA, table_name)

    with ingest_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
                table_identifier,
                sql.SQL(", ").join(column_definitions),
            )
        )
        cursor.execute(sql.SQL("TRUNCATE TABLE {}").format(table_identifier))
        copy_query = sql.SQL("COPY {} ({}) FROM STDIN").format(
            table_identifier,
            sql.SQL(", ").join(sql.Identifier(str(column)) for column in frame.columns),
        )
        with cursor.copy(copy_query) as copy:
            for row in frame.itertuples(index=False, name=None):
                copy.write_row([None if pd.isna(value) else value for value in row])
        connection.commit()
    return table_name


def inspect_dataset(table_name: str, sample_size: int = 5) -> DatasetInfo:
    table_identifier = sql.Identifier(ANALYSIS_SCHEMA, table_name)
    with ingest_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (ANALYSIS_SCHEMA, table_name),
        )
        columns = {name: dtype for name, dtype in cursor.fetchall()}
        if not columns:
            raise ValueError(f"Dataset table does not exist: {table_name}")

        cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(table_identifier))
        count_row = cursor.fetchone()
        if count_row is None:
            raise RuntimeError("PostgreSQL did not return the dataset row count")
        n_rows = int(count_row[0])

        null_expressions = [
            sql.SQL("COUNT(*) FILTER (WHERE {} IS NULL) AS {}").format(
                sql.Identifier(column), sql.Identifier(column)
            )
            for column in columns
        ]
        cursor.execute(
            sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(null_expressions), table_identifier
            )
        )
        null_row = cursor.fetchone()
        if null_row is None:
            raise RuntimeError("PostgreSQL did not return the null summary")
        null_summary = dict(zip(columns, null_row, strict=True))

        cursor.execute(
            sql.SQL("SELECT * FROM {} LIMIT %s").format(table_identifier),
            (sample_size,),
        )
        if cursor.description is None:
            raise RuntimeError("PostgreSQL did not return sample row metadata")
        names = [description.name for description in cursor.description]
        raw_rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        from analyst_agent.pii import redact_sample_rows

        sample_rows = redact_sample_rows(raw_rows)

    return {
        "table_name": f"{ANALYSIS_SCHEMA}.{table_name}",
        "columns": columns,
        "n_rows": n_rows,
        "null_summary": {key: int(value) for key, value in null_summary.items()},
        "sample_rows": sample_rows,
    }
