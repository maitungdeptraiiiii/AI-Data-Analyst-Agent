from datetime import date, datetime
from decimal import Decimal
from typing import Any


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


def extract_metrics(rows: list[dict[str, object]]) -> dict[str, float]:
    if len(rows) != 1:
        return {}
    metrics: dict[str, float] = {}
    for key, value in rows[0].items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float | Decimal):
            metrics[key] = float(value)
    return metrics
