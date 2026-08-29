from psycopg import errors

from analyst_agent.errors import SQLPolicyError, SQLResultLimitError, classify_sql_error


def test_classify_postgres_syntax_error_as_retryable() -> None:
    result = classify_sql_error(errors.SyntaxError("invalid SQL"))
    assert result["code"] == "42601"
    assert result["category"] == "retryable_sql"
    assert result["retryable"] is True


def test_classify_readonly_violation_as_blocked() -> None:
    result = classify_sql_error(errors.ReadOnlySqlTransaction("write denied"))
    assert result["code"] == "25006"
    assert result["category"] == "blocked_sql"
    assert result["retryable"] is False


def test_classify_connection_error_as_infrastructure() -> None:
    result = classify_sql_error(errors.ConnectionFailure("connection lost"))
    assert result["code"] == "08006"
    assert result["category"] == "infrastructure"
    assert result["retryable"] is False


def test_classify_result_limit_as_retryable() -> None:
    result = classify_sql_error(SQLResultLimitError("too many rows"))
    assert result["category"] == "retryable_sql"
    assert result["retryable"] is True


def test_classify_policy_violation_as_blocked() -> None:
    result = classify_sql_error(SQLPolicyError("write statement"))
    assert result["category"] == "blocked_sql"
    assert result["retryable"] is False
