from typing import cast

from analyst_agent.cli import initial_state
from analyst_agent.graph import route_after_critic, route_after_replan
from analyst_agent.nodes import critic, replan
from analyst_agent.schemas import CriticOutput, ReplanOutput
from analyst_agent.state import AgentState, AnalysisStep


def phase3_state(**updates: object) -> AgentState:
    state = initial_state("Why did July revenue decrease?", "data/sample_sales.csv")
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


def successful_step(step_id: str = "step_1") -> AnalysisStep:
    return {
        "step_id": step_id,
        "instruction": "Calculate monthly revenue",
        "tool": "sql",
        "code": "SELECT date_trunc('month', date), SUM(revenue) FROM analysis.dataset_test",
        "rows": [{"month": "2026-07-01", "revenue": 25_000}],
        "metrics": {},
        "success": True,
        "error": None,
        "attempts": [],
    }


def failed_step() -> AnalysisStep:
    return {
        "step_id": "step_2",
        "instruction": "Break down revenue by region",
        "tool": "sql",
        "code": "SELECT secret_debug_sql",
        "rows": [],
        "metrics": {},
        "success": False,
        "error": "secret database error that Critic must not receive",
        "attempts": [
            {
                "attempt": 1,
                "tool": "sql",
                "code": "SELECT secret_debug_sql",
                "success": False,
                "error_category": "retryable_sql",
                "error_code": "42601",
                "error_message": "secret attempt details",
            }
        ],
    }


def test_critic_appends_review_and_omits_failed_debug_details(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: list[object] = []

    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is CriticOutput
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            captured.extend(messages)
            return CriticOutput(
                verdict="retry",
                reason="Regional evidence is missing",
                missing=["Compare July revenue by region with June"],
            )

    monkeypatch.setattr(critic, "create_chat_model", lambda role: FakeModel())
    state = phase3_state(analysis_log=[successful_step(), failed_step()])
    update = critic.review_evidence(state)

    history = cast(list[dict[str, object]], update["critic_history"])
    prompt = str(captured)
    assert update["critic_verdict"] == "retry"
    assert history[0]["round"] == 1
    assert "Break down revenue by region" in prompt
    assert "secret database error" not in prompt
    assert "secret_debug_sql" not in prompt
    assert "secret attempt details" not in prompt


def test_critic_routes_pass_retry_and_cap() -> None:
    assert route_after_critic(phase3_state(critic_verdict="pass")) == "charts"
    assert (
        route_after_critic(
            phase3_state(critic_verdict="retry", critic_retry_count=0, critic_max_retries=2)
        )
        == "replan"
    )
    assert (
        route_after_critic(
            phase3_state(critic_verdict="retry", critic_retry_count=2, critic_max_retries=2)
        )
        == "bailout"
    )


def test_replanner_increments_critic_budget_and_preserves_evidence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is ReplanOutput
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            return ReplanOutput(
                rationale="Regional comparison is needed",
                additional_plan=["Compare June and July revenue by region"],
            )

    monkeypatch.setattr(replan, "create_chat_model", lambda role: FakeModel())
    evidence = [successful_step()]
    state = phase3_state(
        analysis_log=evidence,
        critic_verdict="retry",
        critic_reason="Regional evidence missing",
        critic_missing=["Compare by region"],
    )
    update = replan.create_additional_plan(state)

    assert update["plan"] == ["Compare June and July revenue by region"]
    assert update["current_step"] == 0
    assert update["critic_retry_count"] == 1
    assert state["analysis_log"] == evidence
    assert state["dataset_info"] is not None


def test_empty_replan_routes_to_report_and_adds_warning(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            return ReplanOutput(rationale="No additional query is possible", additional_plan=[])

    monkeypatch.setattr(replan, "create_chat_model", lambda role: FakeModel())
    state = phase3_state(critic_verdict="retry", critic_missing=["Unavailable dimension"])
    update = replan.create_additional_plan(state)
    state.update(update)  # type: ignore[typeddict-item]
    assert route_after_replan(state) == "report"
    assert state["analysis_warnings"]


def test_critic_bailout_adds_visible_warning() -> None:
    state = phase3_state(critic_missing=["Regional comparison"], critic_retry_count=2)
    update = critic.bailout_after_critic(state)
    warnings = cast(list[str], update["analysis_warnings"])
    assert "Regional comparison" in warnings[0]
