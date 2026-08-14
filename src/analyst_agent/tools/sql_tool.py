import atexit
import re
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from analyst_agent.config import get_settings
from analyst_agent.errors import SQLPolicyError, SQLResultLimitError
from analyst_agent.serialization import normalize_json_value

_FORBIDDEN_SQL = re.compile(
    r"\b(ALTER|CALL|COPY|CREATE|DELETE|DO|DROP|EXECUTE|GRANT|INSERT|MERGE|REVOKE|"
    r"TRUNCATE|UPDATE|VACUUM)\b",
    re.IGNORECASE,
)
_executor_pool: ConnectionPool[Connection[Any]] | None = None


def validate_readonly_sql(query: str) -> str:
    cleaned = query.strip()
    if not cleaned:
        raise SQLPolicyError("SQL query is empty")
    if _contains_statement_separator(cleaned.rstrip(";")):
        raise SQLPolicyError("Only one SQL statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise SQLPolicyError("Only SELECT or WITH queries are allowed")
    if _FORBIDDEN_SQL.search(cleaned):
        raise SQLPolicyError("SQL contains a forbidden write or administrative keyword")
    return cleaned.rstrip(";")


def _contains_statement_separator(query: str) -> bool:
    """Find semicolons outside quoted strings and PostgreSQL dollar-quoted strings."""
    single_quoted = False
    double_quoted = False
    dollar_tag: str | None = None
    index = 0

    while index < len(query):
        if dollar_tag is not None:
            if query.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue

        character = query[index]
        if single_quoted:
            if character == "'" and index + 1 < len(query) and query[index + 1] == "'":
                index += 2
                continue
            if character == "'":
                single_quoted = False
            index += 1
            continue

        if double_quoted:
            if character == '"' and index + 1 < len(query) and query[index + 1] == '"':
                index += 2
                continue
            if character == '"':
                double_quoted = False
            index += 1
            continue

        if character == "'":
            single_quoted = True
        elif character == '"':
            double_quoted = True
        elif character == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", query[index:])
            if match:
                dollar_tag = match.group(0)
                index += len(dollar_tag)
                continue
        elif character == ";":
            return True
        index += 1
    return False


def get_executor_pool() -> ConnectionPool[Connection[Any]]:
    global _executor_pool
    if _executor_pool is None:
        _executor_pool = ConnectionPool(
            conninfo=get_settings().postgres_executor_dsn,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        atexit.register(_executor_pool.close)
    return _executor_pool


def execute_readonly_sql(query: str, max_rows: int = 200) -> list[dict[str, object]]:
    safe_query = validate_readonly_sql(query)
    with get_executor_pool().connection() as connection:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            with connection.cursor() as cursor:
                cursor.execute(safe_query)
                rows = cursor.fetchmany(max_rows + 1)
                if len(rows) > max_rows:
                    raise SQLResultLimitError(f"Query returned more than {max_rows} rows")
                return [normalize_json_value(dict(row)) for row in rows]
