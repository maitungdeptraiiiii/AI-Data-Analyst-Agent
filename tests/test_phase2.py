from typing import cast

from psycopg import errors

from analyst_agent.cli import initial_state
from analyst_agent.errors import SQLPolicyError, SQLResultLimitError, classify_sql_error
from analyst_agent.graph import route_after_sql
from analyst_agent.nodes import executor, fix_and_retry
from analyst_agent.schemas import SQLFixOutput
from analyst_agent.state import AgentState


def phase2_state(**updates: object) -> AgentState:
    state = initial_state("Analyze revenue", "data/sample_sales.csv")
    state.update(  # type: ignore[typeddict-item]
        {
            "planner_status": "ready",
            "dataset_info": {
                "table_name": "analysis.dataset_test",
                "columns": {"date": "timestamp with time zone", "revenue": "bigint"},
                "n_rows": 3,
                "null_summary": {"date": 0, "revenue": 0},
                "sample_rows": [],
            },
            "plan": ["Calculate monthly revenue"],
            **updates,
        }
    )
    return state


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


def test_retryable_error_routes_to_fix() -> None:
    state = phase2_state(
        current_error={
            "category": "retryable_sql",
            "code": "42601",
            "message": "syntax error",
            "retryable": True,
        },
        execution_retry_count=0,
        execution_max_retries=2,
    )
    assert route_after_sql(state) == "retry"


def test_retry_cap_routes_to_finalize() -> None:
    state = phase2_state(
        current_error={
            "category": "retryable_sql",
            "code": "42601",
            "message": "syntax error",
            "retryable": True,
        },
        execution_retry_count=2,
        execution_max_retries=2,
    )
    assert route_after_sql(state) == "finalize"


def test_blocked_error_routes_to_finalize_without_retry() -> None:
    state = phase2_state(
        current_error={
            "category": "blocked_sql",
            "code": "25006",
            "message": "read-only transaction",
            "retryable": False,
        }
    )
    assert route_after_sql(state) == "finalize"


def test_execute_step_appends_failed_attempt(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state = phase2_state(
        current_tool="sql",
        current_code="SELECT missing FROM analysis.dataset_test",
        current_purpose="Calculate monthly revenue",
    )

    def fail_sql(_query: str) -> list[dict[str, object]]:
        raise errors.UndefinedColumn("column missing does not exist")

    monkeypatch.setattr(executor, "execute_readonly_sql", fail_sql)
    update = executor.execute_step(state)
    attempts = cast(list[dict[str, object]], update["current_attempts"])
    error = cast(dict[str, object], update["current_error"])
    assert len(attempts) == 1
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["success"] is False
    assert error["code"] == "42703"


def test_union_order_by_syntax_error_enters_retry_flow(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    failed_sql = """SELECT month, revenue FROM monthly
UNION ALL
SELECT NULL, SUM(revenue) FROM monthly
ORDER BY date_trunc('month', month)"""
    state = phase2_state(
        current_tool="sql",
        current_code=failed_sql,
        current_purpose="Compare monthly revenue and include a summary",
    )

    def fail_union_order_by(_query: str) -> list[dict[str, object]]:
        raise errors.SyntaxError(
            "invalid UNION/INTERSECT/EXCEPT ORDER BY clause: "
            "Only result column names can be used, not expressions or functions"
        )

    monkeypatch.setattr(executor, "execute_readonly_sql", fail_union_order_by)
    update = executor.execute_step(state)
    state.update(update)  # type: ignore[typeddict-item]

    assert state["current_error"] is not None
    assert state["current_error"]["code"] == "42601"
    assert route_after_sql(state) == "retry"


def test_fix_and_retry_updates_sql_and_retry_state(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    corrected_sql = """WITH combined AS (
    SELECT month, revenue FROM monthly
    UNION ALL
    SELECT NULL, SUM(revenue) FROM monthly
)
SELECT * FROM combined ORDER BY month"""
    captured_messages: list[object] = []

    class FakeStructuredModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is SQLFixOutput
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            captured_messages.extend(messages)
            return SQLFixOutput(
                diagnosis="ORDER BY after UNION uses an expression not present in the output",
                changes=["Wrapped the UNION in a CTE", "Ordered by the output column"],
                sql=corrected_sql,
            )

    monkeypatch.setattr(
        fix_and_retry,
        "create_chat_model",
        lambda role: FakeStructuredModel(),
    )
    state = phase2_state(
        current_tool="sql",
        current_code="SELECT month FROM monthly UNION ALL SELECT NULL ORDER BY lower(month)",
        current_purpose="Compare monthly revenue and include a summary",
        current_rows=[{"stale": True}],
        current_error={
            "category": "retryable_sql",
            "code": "42601",
            "message": "invalid UNION/INTERSECT/EXCEPT ORDER BY clause",
            "retryable": True,
        },
        current_attempts=[
            {
                "attempt": 1,
                "sql": "SELECT month FROM monthly UNION ALL SELECT NULL ORDER BY lower(month)",
                "success": False,
                "error_category": "retryable_sql",
                "error_code": "42601",
                "error_message": "invalid UNION/INTERSECT/EXCEPT ORDER BY clause",
            }
        ],
        execution_retry_count=0,
    )

    update = fix_and_retry.fix_and_retry(state)

    assert update["current_code"] == corrected_sql
    assert update["execution_retry_count"] == 1
    assert update["current_error"] is None
    assert update["current_rows"] == []
    assert "Compare monthly revenue and include a summary" in str(captured_messages)


def test_finalize_preserves_attempts_and_resets_retry_state() -> None:
    attempt = {
        "attempt": 1,
        "tool": "sql",
        "code": "SELECT SUM(revenue) FROM analysis.dataset_test",
        "success": True,
        "error_category": None,
        "error_code": None,
        "error_message": None,
    }
    state = phase2_state(
        current_tool="sql",
        current_code=attempt["code"],
        current_purpose="Calculate monthly revenue",
        current_rows=[{"sum": 100}],
        current_attempts=[attempt],
        execution_retry_count=1,
    )
    update = executor.finalize_step(state)
    log = cast(list[dict[str, object]], update["analysis_log"])
    assert log[0]["attempts"] == [attempt]
    assert update["current_step"] == 1
    assert update["current_attempts"] == []
    assert update["current_code"] is None
    assert update["execution_retry_count"] == 0
