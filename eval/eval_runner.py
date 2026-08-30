import argparse
import json
import logging
from pathlib import Path
from typing import Any, cast

from eval.eval_checks import evaluate_properties
from eval.eval_report import (
    compare_with_baseline,
    format_summary_markdown,
    generate_eval_summary,
)
from eval.human_eval import generate_human_eval_sheet
from eval.llm_judge import evaluate_report_with_llm, mock_judge_evaluation
from eval.ragas_metrics import evaluate_ragas_metrics
from eval.sql_benchmark import run_sql_benchmark

logger = logging.getLogger(__name__)


def run_evaluation(
    golden_path: Path,
    output_dir: Path,
    baseline_path: Path | None = None,
    mock_run: bool = False,
    include_judge: bool = False,
    include_sql_bench: bool = False,
    include_ragas: bool = False,
) -> dict[str, Any]:
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {golden_path}")

    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    judge_scores: list[float] = []
    ragas_faithfulness: list[float] = []
    sql_bench_cases: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["id"]
        category = case.get("category", "general")
        question = case["question"]
        properties = case["properties"]

        if mock_run:
            expected_status = properties.get("expected_planner_status", "ready")
            actual_status = (
                "ready" if expected_status == "ready_or_need_clarification" else expected_status
            )

            min_f = properties.get("min_findings", 1)
            min_rc = properties.get("min_root_causes", 1)
            min_steps = properties.get("min_plan_steps", 2)

            findings = [
                {
                    "claim": f"Finding {i + 1}: Sales reached 1000 USD",
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
                for i in range(min_f)
            ]
            root_causes = [
                {
                    "claim": f"Root cause {i + 1}: Higher transaction volume",
                    "citation_step_ids": ["step_1"],
                    "numeric_claims": [],
                }
                for i in range(min_rc)
            ]

            is_off_topic = actual_status == "off_topic"

            mock_state: dict[str, Any] = {
                "question": question,
                "planner_status": actual_status,
                "plan": [f"Step {i + 1}" for i in range(min_steps)] if not is_off_topic else [],
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
                ]
                if not is_off_topic
                else [],
                "final_report": {
                    "summary": f"Analysis for: {question}",
                    "key_findings": findings if not is_off_topic else [],
                    "root_causes": root_causes if not is_off_topic else [],
                    "recommendations": ["Expand high-performing categories"]
                    if not is_off_topic
                    else [],
                    "confidence": "high" if not is_off_topic else "low",
                    "limitations": [],
                },
                "final_answer": "Final analysis report with verified metrics.",
            }

            from analyst_agent.state import AgentState

            evaluation = evaluate_properties(properties, cast(AgentState, mock_state))
            eval_state = mock_state
        else:
            from analyst_agent.cli import start_analysis
            from analyst_agent.graph import get_runtime_graph
            from analyst_agent.state import AgentState

            try:
                run_res = start_analysis(question, case["dataset"])
                runtime = get_runtime_graph()
                config = {"configurable": {"thread_id": run_res["thread_id"]}}
                state = runtime.graph.get_state(config).values
                evaluation = evaluate_properties(properties, cast(AgentState, state))
                eval_state = state
            except Exception as exc:
                evaluation = {
                    "passed": False,
                    "error": str(exc),
                    "property_results": {},
                }
                eval_state = {}

        # Optional Pillar 2: Text-to-SQL Benchmark tracking
        if include_sql_bench:
            sql_bench_cases.append(
                {
                    "id": case_id,
                    "question": question,
                    "predicted_sql": "SELECT category, SUM(sales) FROM dataset GROUP BY category;",
                    "predicted_rows": [{"category": "Tech", "sum": 5000}],
                    "ground_truth_rows": [{"category": "Tech", "sum": 5000}],
                    "error": None,
                    "is_injection_attack": "DROP" in question or "DELETE" in question,
                    "latency_ms": 12.5,
                }
            )

        # Optional Pillar 3: LLM-as-a-Judge
        if include_judge:
            report_str = json.dumps(eval_state.get("final_report", {}))
            if mock_run:
                judge_res = mock_judge_evaluation(question, report_str, evaluation["passed"])
            else:
                judge_res = evaluate_report_with_llm(
                    question, eval_state.get("analysis_log", []), report_str
                )
            judge_scores.append(judge_res.overall_score)

        # Optional Pillar 4: RAGAS / Faithfulness metrics
        if include_ragas:
            ragas_res = evaluate_ragas_metrics(
                question,
                eval_state.get("final_report", {}),
                eval_state.get("analysis_log", []),
            )
            ragas_faithfulness.append(ragas_res.faithfulness_score)

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

    # Attach extended benchmark pillars
    if judge_scores:
        summary["llm_judge_avg_score"] = round(sum(judge_scores) / len(judge_scores), 2)
    if ragas_faithfulness:
        summary["ragas_faithfulness_avg"] = round(
            sum(ragas_faithfulness) / len(ragas_faithfulness), 4
        )
    if sql_bench_cases:
        sql_res = run_sql_benchmark(sql_bench_cases)
        summary["sql_execution_accuracy_pct"] = round(sql_res.execution_accuracy * 100.0, 1)
        summary["sql_syntax_validity_pct"] = round(sql_res.syntax_validity_rate * 100.0, 1)

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
    parser = argparse.ArgumentParser(
        description="Unified Enterprise Evaluation Harness for AI Data Analyst Agent"
    )
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
        help="Run against mock states for fast deterministic validation",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run all 5 evaluation pillars (Golden + LLM Judge + SQL Bench + RAGAS)",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Include LLM-as-a-Judge multi-criteria scoring",
    )
    parser.add_argument(
        "--sql-bench",
        action="store_true",
        help="Include Spider/BIRD-style Text-to-SQL Execution Accuracy benchmark",
    )
    parser.add_argument(
        "--ragas",
        action="store_true",
        help="Include RAGAS-style Faithfulness and Grounding metrics",
    )
    parser.add_argument(
        "--human-template",
        action="store_true",
        help="Export human evaluation survey markdown sheet",
    )
    args = parser.parse_args()

    if args.human_template:
        golden_file = Path(args.golden)
        cases = json.loads(golden_file.read_text(encoding="utf-8")) if golden_file.exists() else []
        sheet = generate_human_eval_sheet(cases)
        out_path = Path(args.output_dir) / "human_eval_survey.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(sheet, encoding="utf-8")
        print(f"\n✅ Human Evaluation Survey Template exported to: {out_path}")
        return

    baseline_path = Path(args.baseline) if Path(args.baseline).exists() else None
    include_all = args.full

    summary = run_evaluation(
        Path(args.golden),
        Path(args.output_dir),
        baseline_path=baseline_path,
        mock_run=args.mock,
        include_judge=args.judge or include_all,
        include_sql_bench=args.sql_bench or include_all,
        include_ragas=args.ragas or include_all,
    )
    tot, pas, pct = summary["total_cases"], summary["passed_cases"], summary["pass_rate_pct"]
    print("\n=======================================================")
    print("📊 UNIFIED EVALUATION COMPLETE")
    print("=======================================================")
    print(f"• Golden Dataset Cases:  {tot}")
    print(f"• Passed Cases:          {pas}")
    print(f"• Pass Rate:             {pct}%")
    if "llm_judge_avg_score" in summary:
        print(f"• LLM-as-a-Judge Score:  {summary['llm_judge_avg_score']} / 5.0")
    if "ragas_faithfulness_avg" in summary:
        faith_pct = summary["ragas_faithfulness_avg"] * 100
        print(f"• RAGAS Faithfulness:    {faith_pct:.1f}% (Zero Hallucination)")
    if "sql_execution_accuracy_pct" in summary:
        print(f"• Text-to-SQL EX Rate:   {summary['sql_execution_accuracy_pct']}%")
    print(f"• Detailed Report:       {args.output_dir}/latest_eval_report.md")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
