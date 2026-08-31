import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

_LABEL_SLUG = re.compile(r"[^a-z0-9]+")


def normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return normalize_json_value(value.item())
    if isinstance(value, dict):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [normalize_json_value(item) for item in value]
    return str(value)


def _numeric_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


def _slugify_label(value: object) -> str:
    slug = _LABEL_SLUG.sub("_", str(value).strip().lower()).strip("_")
    return slug or "value"


def extract_metrics(rows: list[dict[str, object]], max_rows: int = 50) -> dict[str, float]:
    """Flatten query results into named metrics the grounding verifier can check.

    A single row is flattened directly (one aggregate query -> one metric per column). A
    breakdown query (e.g. revenue by month) instead returns one row per category, so metrics
    are keyed as ``{numeric_column}__{label}`` using the one non-numeric column as the label,
    letting the reporter still cite a specific, verifiable number per category. Ambiguous
    shapes (no single label column, or duplicate labels) yield no metrics rather than guessing.
    """
    if not rows:
        return {}
    if len(rows) == 1:
        metrics: dict[str, float] = {}
        for key, value in rows[0].items():
            numeric = _numeric_value(value)
            if numeric is not None:
                metrics[key] = numeric
        return metrics

    sample_rows = rows[:max_rows]
    columns = list(sample_rows[0].keys())
    numeric_columns = [
        column
        for column in columns
        if all(_numeric_value(row.get(column)) is not None for row in sample_rows)
    ]
    label_columns = [column for column in columns if column not in numeric_columns]
    if len(label_columns) != 1 or not numeric_columns:
        return {}

    label_column = label_columns[0]
    labels = [str(row[label_column]) for row in sample_rows]
    if len(set(labels)) != len(labels):
        return {}

    metrics = {}
    for row in sample_rows:
        slug = _slugify_label(row[label_column])
        for column in numeric_columns:
            numeric = _numeric_value(row[column])
            assert numeric is not None
            metrics[f"{column}__{slug}"] = numeric
    return metrics
