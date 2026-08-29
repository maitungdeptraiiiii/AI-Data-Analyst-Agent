import argparse
import json
import logging
from pathlib import Path
from typing import Any

from eval.eval_checks import evaluate_properties
from eval.eval_report import (
    compare_with_baseline,
    format_summary_markdown,
    generate_eval_summary,
)

logger = logging.getLogger(__name__)


def run_evaluation(
    golden_path: Path,
    output_dir: Path,
    baseline_path: Path | None = None,
    mock_run: bool = False,
) -> dict[str, Any]:
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {golden_path}")

    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["id"]
        category = case.get("category", "general")
        question = case["question"]
        properties = case["properties"]

        if mock_run:
            # Mock successful state matching common properties
            mock_state: dict[str, Any] = {
                "question": question,
                "planner_status": case.get("properties", {}).get(
                    "expected_planner_status", "ready"
                ),
                "plan": ["Calculate monthly metrics", "Breakdown by category"],
                "analysis_log": [
                    {
                        "step_id": "step_1",
                        "instruction": "Calculate monthly metrics",
                        "tool": "sql",
                        "code": "SELECT 1",
                        "rows": [{"sales": 1000}],
                        "metrics": {"sales": 1000.0},
                        "success": True,
                        "error": None,
                        "attempts": [{"attempt": 1, "success": True, "error_category": None}],
                    }
                ],
                "final_report": {
                    "summary": f"Analysis for: {question}",
                    "key_findings": [
                        {
                            "claim": "Sales reached 1000 USD",
                            "citation_step_ids": ["step_1"],
                            "numeric_claims": [
                                {
                                    "citation_step_id": "step_1",
                                    "metric_name": "sales",
                                    "claimed_value": 1000.0,
                                    "tolerance_pct": 1.0,
                                }
                            ],
                        }
                    ],
                    "root_causes": (
                        [
                            {
                                "claim": "Loss identified in Central",
                                "citation_step_ids": ["step_1"],
                                "numeric_claims": [],
                            }
                        ]
                        if category == "root_cause"
                        else []
                    ),
                    "recommendations": ["Optimize discounting strategy"],
                    "chart_paths": [],
                    "confidence": "high",
                    "limitations": [],
                },
            }
            if case.get("properties", {}).get("no_sql_executed"):
                mock_state["analysis_log"] = []
                mock_state["planner_status"] = "off_topic"
            evaluation = evaluate_properties(properties, mock_state)  # type: ignore[arg-type]
        else:
            # Live execution via analyst-agent CLI / runtime
            try:
                from analyst_agent.cli import start_analysis
                from analyst_agent.graph import get_runtime_graph

                # Start real run
                run_res = start_analysis(question, case["dataset"])
                runtime = get_runtime_graph()
                config = {"configurable": {"thread_id": run_res["thread_id"]}}
                state = runtime.graph.get_state(config).values
                evaluation = evaluate_properties(properties, state)
            except Exception as exc:
                evaluation = {
                    "passed": False,
                    "error": str(exc),
                    "property_results": {},
                }

        results.append(
            {
                "id": case_id,
                "category": category,
                "question": question,
                "passed": evaluation["passed"],
                "details": evaluation.get("property_results", {}),
            }
        )

    summary = generate_eval_summary(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_file = output_dir / "latest_eval_results.json"
    results_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    comparison = None
    if baseline_path:
        comparison = compare_with_baseline(summary, baseline_path)

    report_md = format_summary_markdown(summary, comparison)
    report_file = output_dir / "latest_eval_report.md"
    report_file.write_text(report_md, encoding="utf-8")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluation harness for AI Data Analyst Agent")
    parser.add_argument(
        "--golden",
        default="eval/golden_dataset.json",
        help="Path to golden dataset JSON",
    )
    parser.add_argument(
        "--output-dir",
        default="eval/results",
        help="Directory to save evaluation results",
    )
    parser.add_argument(
        "--baseline",
        default="eval/baselines/baseline_v1.json",
        help="Path to baseline file for regression testing",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run against mock states for fast validation",
    )
    args = parser.parse_args()

    baseline_path = Path(args.baseline) if Path(args.baseline).exists() else None
    summary = run_evaluation(
        Path(args.golden),
        Path(args.output_dir),
        baseline_path=baseline_path,
        mock_run=args.mock,
    )
    tot, pas, pct = summary["total_cases"], summary["passed_cases"], summary["pass_rate_pct"]
    print(f"\nEvaluation Complete! Total: {tot}, Passed: {pas}, Pass Rate: {pct}%")


if __name__ == "__main__":
    main()
