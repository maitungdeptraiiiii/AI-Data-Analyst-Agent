import builtins
import json
import math
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql

configuration = json.loads(Path("/run/input/input.json").read_text())
schema_name, table_name = configuration["table_name"].split(".", 1)

# The AST guard (python_guard.py) is a static, best-effort check run on the host before
# this container starts — it can be bypassed by aliasing a forbidden name (e.g.
# `imp = __import__`). Restricting the runtime builtins is a second, independent layer:
# even a successful alias has nothing dangerous left to call.
_SAFE_BUILTIN_NAMES = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "frozenset",
    "int", "isinstance", "len", "list", "map", "max", "min", "print", "range", "round",
    "set", "sorted", "str", "sum", "tuple", "type", "zip",
    "ArithmeticError", "Exception", "IndexError", "KeyError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
}
SAFE_BUILTINS = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}


def load_dataset():
    with psycopg.connect(configuration["database_dsn"]) as connection:
        query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema_name, table_name))
        return pd.read_sql(query.as_string(connection), connection)


namespace = {"pd": pd, "np": np, "load_dataset": load_dataset}
stdout = StringIO()
try:
    code = Path("/run/input/generated.py").read_text(encoding="utf-8")
    with redirect_stdout(stdout):
        exec(compile(code, "generated.py", "exec"), {"__builtins__": SAFE_BUILTINS}, namespace)
    metrics = namespace.get("metrics")
    result = namespace.get("result")
    if not isinstance(metrics, dict):
        raise TypeError("Generated code must assign a metrics dict")
    safe_metrics = {str(k): float(v) for k, v in metrics.items()}
    non_finite = [k for k, v in safe_metrics.items() if not math.isfinite(v)]
    if non_finite:
        raise ValueError(f"metrics contains non-finite values: {', '.join(non_finite)}")
    if isinstance(result, pd.DataFrame):
        rows = result.head(configuration["max_output_rows"]).to_dict(orient="records")
    elif isinstance(result, list):
        rows = result[: configuration["max_output_rows"]]
    else:
        raise TypeError("Generated code must assign result as DataFrame or list")
    payload = {
        "success": True,
        "rows": rows,
        "metrics": safe_metrics,
        "error": None,
    }
except Exception as exc:
    payload = {
        "success": False,
        "rows": [],
        "metrics": {},
        "error": {
            "category": "retryable_python",
            "code": type(exc).__name__,
            "message": str(exc)[:2000],
            "retryable": True,
        },
    }
Path("/run/output/output.json").write_text(json.dumps(payload, default=str), encoding="utf-8")
