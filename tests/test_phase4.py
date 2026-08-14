from pathlib import Path
from typing import cast

import pytest

from analyst_agent.charts import ChartValidationError, create_chart, validate_chart_spec
from analyst_agent.cli import initial_state
from analyst_agent.graph import route_after_chart_plan, route_after_critic
from analyst_agent.nodes import chart_creator, chart_planner, reporter
from analyst_agent.schemas import ChartPlanOutput, ChartSpec, FinalReport, Finding
from analyst_agent.state import AgentState, AnalysisStep, FinalReportData


def chart_step(success: bool = True) -> AnalysisStep:
    return {
        "step_id": "step_1",
        "instruction": "Calculate monthly revenue",
        "tool": "sql",
        "code": "SELECT month, revenue FROM sales",
        "rows": [
            {"month": "2026-07-01", "revenue": 25_000},
            {"month": "2026-06-01", "revenue": 33_000},
        ],
        "metrics": {},
        "success": success,
        "error": None if success else "failed",
        "attempts": [],
    }


def phase4_state(**updates: object) -> AgentState:
    state = initial_state("Why did July revenue decrease?", "data/sample_sales.csv")
    state.update(  # type: ignore[typeddict-item]
        {
            "planner_status": "ready",
            "plan": ["Calculate monthly revenue"],
            "analysis_log": [chart_step()],
            "critic_verdict": "pass",
            **updates,
        }
    )
    return state


def line_spec(**updates: object) -> ChartSpec:
    data = {
        "title": "Monthly revenue",
        "chart_type": "line",
        "source_step_id": "step_1",
        "x_column": "month",
        "y_column": "revenue",
        "series_column": None,
        "x_label": "Month",
        "y_label": "Revenue",
        "description": "Revenue trend by month",
        **updates,
    }
    return ChartSpec.model_validate(data)


def test_chart_validation_rejects_unknown_or_failed_step() -> None:
    with pytest.raises(ChartValidationError, match="successful"):
        validate_chart_spec(line_spec(source_step_id="missing"), [chart_step()])
    with pytest.raises(ChartValidationError, match="successful"):
        validate_chart_spec(line_spec(), [chart_step(success=False)])


def test_chart_validation_rejects_missing_column() -> None:
    with pytest.raises(ChartValidationError, match="columns"):
        validate_chart_spec(line_spec(y_column="profit"), [chart_step()])


def test_chart_render_writes_safe_png(tmp_path: Path) -> None:
    artifact = create_chart(line_spec(title="../../unsafe"), [chart_step()], tmp_path, 1)
    output = Path(artifact["path"])
    assert output.is_file()
    assert output.parent == tmp_path.resolve()
    assert output.name == "chart_1_step_1.png"
    assert output.read_bytes().startswith(b"\x89PNG")


def test_sparse_line_chart_downgrades_to_bar(tmp_path: Path) -> None:
    # Only 2 points: a line here would falsely imply a smooth trend between them.
    artifact = create_chart(line_spec(), [chart_step()], tmp_path, 1)
    assert artifact["chart_type"] == "bar"


def test_line_chart_with_enough_points_stays_line(tmp_path: Path) -> None:
    step: AnalysisStep = {
        "step_id": "step_1",
        "instruction": "Calculate monthly revenue",
        "tool": "sql",
        "code": "SELECT month, revenue FROM sales",
        "rows": [
            {"month": "2026-04-01", "revenue": 20_000},
            {"month": "2026-05-01", "revenue": 22_000},
            {"month": "2026-06-01", "revenue": 33_000},
            {"month": "2026-07-01", "revenue": 25_000},
        ],
        "metrics": {},
        "success": True,
        "error": None,
        "attempts": [],
    }
    artifact = create_chart(line_spec(), [step], tmp_path, 1)
    assert artifact["chart_type"] == "line"


def test_grouped_bar_chart_renders_with_series(tmp_path: Path) -> None:
    step: AnalysisStep = {
        "step_id": "step_1",
        "instruction": "Calculate revenue by month and product",
        "tool": "sql",
        "code": "SELECT month, product, revenue FROM sales",
        "rows": [
            {"month": "2026-06-01", "product": "Laptop", "revenue": 18_000},
            {"month": "2026-06-01", "product": "Phone", "revenue": 15_000},
            {"month": "2026-07-01", "product": "Laptop", "revenue": 11_000},
            {"month": "2026-07-01", "product": "Phone", "revenue": 14_000},
        ],
        "metrics": {},
        "success": True,
        "error": None,
        "attempts": [],
    }
    spec = line_spec(chart_type="bar", series_column="product")
    artifact = create_chart(spec, [step], tmp_path, 1)
    output = Path(artifact["path"])
    assert output.is_file()
    assert output.read_bytes().startswith(b"\x89PNG")


def test_chart_planner_stores_serializable_dict_and_omits_failed_steps(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: list[object] = []

    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is ChartPlanOutput
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            captured.extend(messages)
            return ChartPlanOutput(should_create=True, reason="Useful", chart=line_spec())

    monkeypatch.setattr(chart_planner, "create_chat_model", lambda role: FakeModel())
    failed = chart_step(False)
    failed["error"] = "secret chart planner must not receive"
    state = phase4_state(analysis_log=[chart_step(), failed])
    update = chart_planner.plan_chart(state)
    assert isinstance(update["chart_plan"], dict)
    assert "secret chart planner" not in str(captured)


def test_chart_routes_are_explicit() -> None:
    assert route_after_critic(phase4_state(critic_verdict="pass")) == "charts"
    assert route_after_chart_plan(phase4_state(chart_plan=None)) == "report"
    assert route_after_chart_plan(phase4_state(chart_plan=line_spec().model_dump())) == "chart"


def test_chart_failure_adds_warning_without_raising(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        chart_creator,
        "create_chart",
        lambda *args: (_ for _ in ()).throw(ChartValidationError("bad chart")),
    )
    update = chart_creator.create_chart_node(phase4_state(chart_plan=line_spec().model_dump()))
    assert "bad chart" in str(update["chart_warning"])
    assert update["analysis_warnings"]


def test_report_constraints_override_paths_warnings_and_confidence() -> None:
    raw = FinalReport(
        summary="Summary",
        key_findings=[Finding(claim="Revenue declined")],
        root_causes=[],
        recommendations=[],
        chart_paths=["invented.png"],
        confidence="high",
        limitations=["Existing limitation"],
    )
    state = phase4_state(
        charts=[
            {
                "chart_id": "chart_1",
                "path": "actual.png",
                "title": "Revenue",
                "description": "Trend",
                "chart_type": "line",
                "source_step_id": "step_1",
            }
        ],
        analysis_warnings=["Evidence cap reached"],
    )
    constrained = reporter.constrain_report(raw, state)
    assert constrained is not raw
    assert constrained.chart_paths == ["actual.png"]
    assert constrained.confidence == "low"
    assert constrained.limitations == ["Existing limitation", "Evidence cap reached"]


def test_reporter_stores_structured_report(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is FinalReport
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            return FinalReport(
                summary="Revenue decreased",
                key_findings=[],
                root_causes=[],
                recommendations=["Review regional performance"],
                chart_paths=[],
                confidence="medium",
                limitations=[],
            )

    monkeypatch.setattr(reporter, "create_chat_model", lambda role: FakeModel())
    update = reporter.create_report(phase4_state())
    final_report = cast(FinalReportData, update["final_report"])
    assert final_report["summary"] == "Revenue decreased"
    assert "Confidence: medium" in str(update["final_answer"])


def test_reporter_prompt_tells_llm_when_a_chart_already_exists(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: list[object] = []

    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            captured.extend(messages)
            return FinalReport(
                summary="Revenue trend shown in the attached chart",
                key_findings=[],
                root_causes=[],
                recommendations=[],
                chart_paths=[],
                confidence="medium",
                limitations=[],
            )

    monkeypatch.setattr(reporter, "create_chat_model", lambda role: FakeModel())
    state = phase4_state(
        charts=[
            {
                "chart_id": "chart_1",
                "path": "actual.png",
                "title": "Monthly revenue trend",
                "description": "Revenue by month",
                "chart_type": "line",
                "source_step_id": "step_1",
            }
        ]
    )
    reporter.create_report(state)
    prompt = str(captured)
    assert "Monthly revenue trend" in prompt
    assert "actual.png" not in prompt
