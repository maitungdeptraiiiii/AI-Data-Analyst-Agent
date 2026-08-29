from typing import cast

from langchain_core.exceptions import OutputParserException

from analyst_agent.cli import initial_state
from analyst_agent.graph import build_graph, route_after_grounding
from analyst_agent.grounding import verify_grounding
from analyst_agent.nodes import grounding_verifier, reporter
from analyst_agent.schemas import FinalReport, Finding, NumericClaim
from analyst_agent.serialization import extract_metrics
from analyst_agent.state import AgentState, AnalysisStep, FinalReportData


def evidence_step(*, success: bool = True) -> AnalysisStep:
    return {
        "step_id": "step_1",
        "instruction": "Calculate revenue",
        "tool": "sql",
        "code": "SELECT SUM(revenue) AS revenue FROM sales",
        "rows": [{"revenue": 100.0}],
        "metrics": {"revenue": 100.0},
        "success": success,
        "error": None if success else "query failed",
        "attempts": [],
    }


def report_data(
    *,
    citation: str = "step_1",
    claimed_value: float = 100.0,
    metric_name: str = "revenue",
) -> FinalReportData:
    return cast(
        FinalReportData,
        FinalReport(
            summary="Revenue result",
            key_findings=[
                Finding(
                    claim=f"Revenue was {claimed_value}",
                    citation_step_ids=[citation],
                    numeric_claims=[
                        NumericClaim(
                            citation_step_id=citation,
                            metric_name=metric_name,
                            claimed_value=claimed_value,
                        )
                    ],
                )
            ],
            root_causes=[],
            recommendations=[],
            confidence="high",
            limitations=[],
        ).model_dump(),
    )


def phase7_state(**updates: object) -> AgentState:
    state = initial_state("What is revenue?", "data/sample_sales.csv")
    state.update(  # type: ignore[typeddict-item]
        {
            "planner_status": "ready",
            "analysis_log": [evidence_step()],
            "draft_report": report_data(),
            **updates,
        }
    )
    return state


def test_grounding_accepts_exact_and_tolerated_numeric_claims() -> None:
    assert verify_grounding(report_data(), [evidence_step()]) == []
    assert verify_grounding(report_data(claimed_value=100.5), [evidence_step()]) == []


def test_grounding_rejects_unknown_failed_and_duplicate_citations() -> None:
    unknown = verify_grounding(report_data(citation="missing"), [evidence_step()])
    failed = verify_grounding(report_data(), [evidence_step(success=False)])
    duplicate = report_data()
    duplicate["key_findings"][0]["citation_step_ids"].append("step_1")

    assert "invalid_citation" in {item["code"] for item in unknown}
    assert "invalid_citation" in {item["code"] for item in failed}
    assert "duplicate_citation" in {
        item["code"] for item in verify_grounding(duplicate, [evidence_step()])
    }


def test_grounding_rejects_mismatch_missing_and_unregistered_numbers() -> None:
    mismatch = verify_grounding(report_data(claimed_value=105), [evidence_step()])
    missing = verify_grounding(
        report_data(metric_name="profit"),
        [evidence_step()],
    )
    unregistered = report_data()
    unregistered["key_findings"][0]["numeric_claims"] = []

    assert "numeric_mismatch" in {item["code"] for item in mismatch}
    assert "missing_metric" in {item["code"] for item in missing}
    assert "unregistered_numeric_literal" in {
        item["code"] for item in verify_grounding(unregistered, [evidence_step()])
    }


def test_non_finite_values_are_not_exposed_as_metrics() -> None:
    assert extract_metrics([{"nan": float("nan"), "infinity": float("inf")}]) == {}


def test_extract_metrics_names_breakdown_rows_by_label() -> None:
    rows = [
        {"month": "2026-06", "revenue": 33000.0},
        {"month": "2026-07", "revenue": 25000.0},
    ]
    assert extract_metrics(rows) == {
        "revenue__2026_06": 33000.0,
        "revenue__2026_07": 25000.0,
    }


def test_extract_metrics_skips_ambiguous_breakdown_shapes() -> None:
    # Two non-numeric columns: no single label column to key metrics by.
    assert (
        extract_metrics(
            [
                {"region": "North", "product": "Laptop", "revenue": 100.0},
                {"region": "South", "product": "Phone", "revenue": 200.0},
            ]
        )
        == {}
    )
    # Duplicate labels would collide into the same metric key.
    assert (
        extract_metrics(
            [
                {"month": "2026-07", "revenue": 100.0},
                {"month": "2026-07", "revenue": 200.0},
            ]
        )
        == {}
    )


def test_grounding_router_retries_then_sanitizes() -> None:
    assert route_after_grounding(phase7_state(grounding_status="valid")) == "finalize"
    assert route_after_grounding(phase7_state(grounding_status="invalid")) == "retry"
    assert (
        route_after_grounding(phase7_state(grounding_status="invalid", grounding_retry_count=2))
        == "sanitize"
    )


def test_graph_wires_sanitizer_through_finalizer_to_end() -> None:
    edges = {
        (edge.source, edge.target)
        for edge in build_graph().get_graph().edges
        if not edge.conditional
    }
    assert ("reporter", "grounding_verifier") in edges
    assert ("sanitize_report", "finalize_report") in edges
    assert ("finalize_report", "__end__") in edges


def test_sanitizer_removes_invalid_finding_and_finalizer_formats() -> None:
    state = phase7_state(
        grounding_violations=[
            {
                "path": "key_findings[0].numeric_claims[0]",
                "code": "numeric_mismatch",
                "message": "wrong value",
            }
        ]
    )
    update = grounding_verifier.sanitize_report(state)
    state.update(update)  # type: ignore[typeddict-item]
    final = grounding_verifier.finalize_report(state)

    report = cast(FinalReportData, final["final_report"])
    assert report["key_findings"] == []
    assert report["confidence"] == "low"
    assert "Confidence: low" in str(final["final_answer"])


def test_reporter_retries_structured_output_parse_once(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = 0

    class FakeModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is FinalReport
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OutputParserException("invalid report")
            return FinalReport.model_validate(report_data())

    monkeypatch.setattr(reporter, "create_chat_model", lambda role: FakeModel())
    update = reporter.create_report(phase7_state())

    assert calls == 2
    assert update["grounding_status"] == "pending"
    assert update["draft_report"] is not None
