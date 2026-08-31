import os
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from analyst_agent.cli import initial_state
from analyst_agent.config import Settings
from analyst_agent.database import infer_temporal_columns
from analyst_agent.graph import route_after_execution, route_after_planner
from analyst_agent.state import AgentState
from analyst_agent.tools.sql_tool import validate_readonly_sql


def state_with(**updates: object) -> AgentState:
    state = initial_state("Analyze revenue", "data/sample_sales.csv")
    state.update(updates)  # type: ignore[typeddict-item]
    return state


def test_settings_accept_openai_as_selected_provider() -> None:
    settings = Settings(
        llm_provider="openai",
        openai_api_key="test-key",
        postgres_ingest_dsn="postgresql://ingest",
        postgres_executor_dsn="postgresql://executor",
        planner_model="gpt-5",
        executor_model="gpt-5",
        reporter_model="gpt-5",
    )
    assert settings.llm_provider == "openai"


def test_settings_accept_gemini_as_selected_provider() -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="test-key",
        postgres_ingest_dsn="postgresql://ingest",
        postgres_executor_dsn="postgresql://executor",
        planner_model="gemini-2.5-flash",
    )
    assert settings.llm_provider == "gemini"


def test_settings_accept_groq_as_selected_provider() -> None:
    settings = Settings(
        llm_provider="groq",
        groq_api_key="test-key",
        postgres_ingest_dsn="postgresql://ingest",
        postgres_executor_dsn="postgresql://executor",
        planner_model="openai/gpt-oss-20b",
    )
    assert settings.llm_provider == "groq"


def test_settings_require_key_for_selected_provider() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(
            llm_provider="openai",
            openai_api_key=None,
            postgres_ingest_dsn="postgresql://ingest",
            postgres_executor_dsn="postgresql://executor",
        )


def test_temporal_inference_converts_date_column_without_touching_labels() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-07-01", None],
            "product": ["2026 model", "Phone", "Laptop"],
        }
    )
    converted = infer_temporal_columns(frame)
    assert pd.api.types.is_datetime64_any_dtype(converted["date"].dtype)
    assert not pd.api.types.is_datetime64_any_dtype(converted["product"].dtype)


def test_temporal_inference_keeps_mostly_invalid_date_column_as_text() -> None:
    frame = pd.DataFrame({"event_date": ["unknown", "not recorded", "2026-07-01"]})
    converted = infer_temporal_columns(frame)
    assert not pd.api.types.is_datetime64_any_dtype(converted["event_date"].dtype)


def test_route_after_planner_ready() -> None:
    state = state_with(planner_status="ready", plan=["Calculate total revenue"])
    assert route_after_planner(state) == "inspect"


def test_route_after_planner_routes_need_clarification() -> None:
    state = state_with(
        planner_status="need_clarification",
        clarification_question="Which year?",
        plan=[],
    )
    assert route_after_planner(state) == "clarify"


def test_route_after_planner_skips_off_topic() -> None:
    state = state_with(planner_status="off_topic", plan=[])
    assert route_after_planner(state) == "report"


def test_route_after_planner_rejects_empty_plan() -> None:
    state = state_with(planner_status="ready", plan=[])
    assert route_after_planner(state) == "report"


def test_route_after_execution_continues() -> None:
    state = state_with(plan=["one", "two"], current_step=1)
    assert route_after_execution(state) == "continue"


def test_route_after_execution_enters_critic_when_done() -> None:
    state = state_with(plan=["one"], current_step=1)
    assert route_after_execution(state) == "critic"


@pytest.mark.parametrize(
    "query",
    [
        "UPDATE analysis.dataset_x SET revenue = 0",
        "WITH changed AS (DELETE FROM analysis.dataset_x RETURNING *) SELECT * FROM changed",
        "SELECT 1; DROP TABLE analysis.dataset_x",
        "COPY analysis.dataset_x TO '/tmp/leak.csv'",
    ],
)
def test_sql_tool_blocks_write_and_admin_statements(query: str) -> None:
    with pytest.raises(ValueError):
        validate_readonly_sql(query)


def test_sql_tool_accepts_select_and_cte() -> None:
    assert validate_readonly_sql("SELECT region, SUM(revenue) FROM analysis.sales GROUP BY region")
    assert validate_readonly_sql("WITH totals AS (SELECT 1 AS n) SELECT n FROM totals")


def test_sql_tool_allows_semicolon_inside_string_literal() -> None:
    query = "SELECT * FROM analysis.sales WHERE product = 'Phone; Pro'"
    assert validate_readonly_sql(query) == query


@pytest.mark.integration
def test_executor_database_role_is_read_only() -> None:
    from psycopg import Error, connect

    dsn = os.getenv("POSTGRES_EXECUTOR_DSN")
    if not dsn:
        pytest.skip("POSTGRES_EXECUTOR_DSN is not configured")
    with connect(dsn) as connection:
        row = connection.execute("SHOW default_transaction_read_only").fetchone()
        assert row is not None and row[0] == "on"
        with pytest.raises(Error):
            connection.execute("CREATE TABLE analysis.must_not_exist (id integer)")


def test_sample_dataset_exists() -> None:
    assert Path("data/sample_sales.csv").is_file()
