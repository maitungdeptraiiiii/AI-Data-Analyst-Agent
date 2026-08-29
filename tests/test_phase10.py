import json
from pathlib import Path
from typing import Any

from eval.eval_checks import (
    check_all_citations_valid,
    check_all_numeric_claims_match,
    check_min_findings,
    check_no_blocked_tool_calls,
)
from eval.eval_report import compare_with_baseline
from eval.eval_runner import run_evaluation


def test_golden_dataset_structure() -> None:
    golden_file = Path("eval/golden_dataset.json")
    assert golden_file.exists()
    cases = json.loads(golden_file.read_text(encoding="utf-8"))
    assert len(cases) == 30
    for case in cases:
        assert "id" in case
        assert "category" in case
        assert "dataset" in case
        assert "question" in case
        assert "properties" in case
        assert len(case["question"]) > 0


def test_check_all_citations_valid() -> None:
    state: dict[str, Any] = {
        "analysis_log": [
            {
                "step_id": "step_1",
                "instruction": "Test",
                "tool": "sql",
                "code": "SELECT 1",
                "rows": [{"val": 10}],
                "metrics": {"val": 10.0},
                "success": True,
                "error": None,
                "attempts": [],
            }
        ]
    }
    report: dict[str, Any] = {
        "summary": "Summary",
        "key_findings": [
            {
                "claim": "Value is 10",
                "citation_step_ids": ["step_1"],
                "numeric_claims": [],
            }
        ],
        "root_causes": [],
        "recommendations": [],
        "chart_paths": [],
        "confidence": "high",
        "limitations": [],
    }

    valid, msg = check_all_citations_valid(report, state)  # type: ignore[arg-type]
    assert valid is True

    # Invalid citation test
    invalid_report = dict(report)
    invalid_report["key_findings"] = [
        {"claim": "Invalid", "citation_step_ids": ["non_existent_step"], "numeric_claims": []}
    ]
    invalid, msg = check_all_citations_valid(invalid_report, state)  # type: ignore[arg-type]
    assert invalid is False


def test_check_all_numeric_claims_match() -> None:
    state: dict[str, Any] = {
        "analysis_log": [
            {
                "step_id": "step_1",
                "instruction": "Calculate revenue",
                "tool": "sql",
                "code": "SELECT 5000",
                "rows": [{"revenue": 5000}],
                "metrics": {"revenue": 5000.0},
                "success": True,
                "error": None,
                "attempts": [],
            }
        ]
    }
    report: dict[str, Any] = {
        "summary": "Revenue report",
        "key_findings": [
            {
                "claim": "Revenue reached 5000",
                "citation_step_ids": ["step_1"],
                "numeric_claims": [
                    {
                        "citation_step_id": "step_1",
                        "metric_name": "revenue",
                        "claimed_value": 5000.0,
                        "tolerance_pct": 1.0,
                    }
                ],
            }
        ],
        "root_causes": [],
        "recommendations": [],
        "chart_paths": [],
        "confidence": "high",
        "limitations": [],
    }

    valid, msg = check_all_numeric_claims_match(report, state)  # type: ignore[arg-type]
    assert valid is True

    # Mismatched number
    mismatch_report = dict(report)
    mismatch_report["key_findings"] = [
        {
            "claim": "Revenue reached 9999",
            "citation_step_ids": ["step_1"],
            "numeric_claims": [
                {
                    "citation_step_id": "step_1",
                    "metric_name": "revenue",
                    "claimed_value": 9999.0,
                    "tolerance_pct": 1.0,
                }
            ],
        }
    ]
    valid, msg = check_all_numeric_claims_match(mismatch_report, state)  # type: ignore[arg-type]
    assert valid is False


def test_check_no_blocked_tool_calls() -> None:
    safe_state: dict[str, Any] = {
        "analysis_log": [
            {"step_id": "step_1", "attempts": [{"attempt": 1, "error_category": "retryable_sql"}]}
        ]
    }
    valid, _ = check_no_blocked_tool_calls(safe_state)  # type: ignore[arg-type]
    assert valid is True

    blocked_state: dict[str, Any] = {
        "analysis_log": [
            {"step_id": "step_1", "attempts": [{"attempt": 1, "error_category": "blocked_sql"}]}
        ]
    }
    valid, _ = check_no_blocked_tool_calls(blocked_state)  # type: ignore[arg-type]
    assert valid is False


def test_check_min_findings() -> None:
    report: dict[str, Any] = {
        "key_findings": [{"claim": "F1"}, {"claim": "F2"}],
    }
    valid, _ = check_min_findings(report, min_count=2)  # type: ignore[arg-type]
    assert valid is True
    invalid, _ = check_min_findings(report, min_count=3)  # type: ignore[arg-type]
    assert invalid is False


def test_eval_runner_mock_execution(tmp_path: Path) -> None:
    summary = run_evaluation(
        Path("eval/golden_dataset.json"),
        tmp_path,
        baseline_path=Path("eval/baselines/baseline_v1.json"),
        mock_run=True,
    )
    assert summary["total_cases"] == 30
    assert summary["passed_cases"] > 0
    assert (tmp_path / "latest_eval_results.json").exists()
    assert (tmp_path / "latest_eval_report.md").exists()


def test_baseline_comparison(tmp_path: Path) -> None:
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps({"pass_rate_pct": 90.0}))

    summary = {"pass_rate_pct": 95.0}
    comp = compare_with_baseline(summary, baseline_file)
    assert comp["diff_pct"] == 5.0
    assert comp["regression_detected"] is False

    # Regression test
    regressed_summary = {"pass_rate_pct": 80.0}
    reg_comp = compare_with_baseline(regressed_summary, baseline_file)
    assert reg_comp["diff_pct"] == -10.0
    assert reg_comp["regression_detected"] is True
