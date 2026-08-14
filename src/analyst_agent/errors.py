import re
from typing import Literal, TypedDict

from psycopg import Error as PsycopgError

_MAX_ERROR_LENGTH = 2000
_CREDENTIAL_PATTERN = re.compile(r"(postgres(?:ql)?://)[^@\s]+@")


def sanitize_error_message(message: str) -> str:
    """Strip embedded DSN credentials before an error reaches any LLM prompt or log."""
    redacted = _CREDENTIAL_PATTERN.sub(r"\1***@", message)
    return redacted[:_MAX_ERROR_LENGTH]


ErrorCategory = Literal[
    "retryable_sql",
    "blocked_sql",
    "retryable_python",
    "blocked_python",
    "sandbox_timeout",
    "sandbox_resource_limit",
    "infrastructure",
    "unknown",
]


class ExecutionError(TypedDict):
    category: ErrorCategory
    code: str | None
    message: str
    retryable: bool


class SQLPolicyError(ValueError):
    """Raised when generated SQL violates the read-only execution policy."""


class SQLResultLimitError(ValueError):
    """Raised when a query must be rewritten to return a bounded result set."""


RETRYABLE_SQLSTATES = {
    "22P02",  # invalid_text_representation
    "42601",  # syntax_error
    "42703",  # undefined_column
    "42803",  # grouping_error
    "42804",  # datatype_mismatch
    "42883",  # undefined_function
    "42P01",  # undefined_table
}
BLOCKED_SQLSTATES = {
    "25006",  # read_only_sql_transaction
    "42501",  # insufficient_privilege
}


def classify_sql_error(exc: Exception) -> ExecutionError:
    if isinstance(exc, SQLResultLimitError):
        return {
            "category": "retryable_sql",
            "code": None,
            "message": sanitize_error_message(str(exc)),
            "retryable": True,
        }
    if isinstance(exc, SQLPolicyError):
        return {
            "category": "blocked_sql",
            "code": None,
            "message": sanitize_error_message(str(exc)),
            "retryable": False,
        }

    code = exc.sqlstate if isinstance(exc, PsycopgError) else None
    if code in RETRYABLE_SQLSTATES:
        category: ErrorCategory = "retryable_sql"
        retryable = True
    elif code in BLOCKED_SQLSTATES:
        category = "blocked_sql"
        retryable = False
    elif code is not None and code.startswith("08"):
        category = "infrastructure"
        retryable = False
    else:
        category = "unknown"
        retryable = False

    return {
        "category": category,
        "code": code,
        "message": sanitize_error_message(str(exc)),
        "retryable": retryable,
    }
