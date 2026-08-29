import json
from pathlib import Path
from typing import Any


def generate_eval_summary(eval_results: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(eval_results)
    passed_cases = sum(1 for r in eval_results if r.get("passed", False))
    pass_rate = (passed_cases / total_cases * 100.0) if total_cases > 0 else 0.0

    by_category: dict[str, dict[str, int]] = {}
    for res in eval_results:
        cat = res.get("category", "unknown")
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0}
        by_category[cat]["total"] += 1
        if res.get("passed", False):
            by_category[cat]["passed"] += 1

    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "pass_rate_pct": round(pass_rate, 2),
        "by_category": by_category,
        "results": eval_results,
    }


def compare_with_baseline(
    current_summary: dict[str, Any], baseline_path: Path
) -> dict[str, Any]:
    if not baseline_path.exists():
        return {
            "has_baseline": False,
            "message": f"Baseline not found at {baseline_path}",
            "regression_detected": False,
        }

    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_pass_rate = baseline_data.get("pass_rate_pct", 0.0)
    current_pass_rate = current_summary.get("pass_rate_pct", 0.0)
    diff = round(current_pass_rate - baseline_pass_rate, 2)

    regression = diff < -5.0  # Alert if pass rate drops more than 5%
    return {
        "has_baseline": True,
        "baseline_pass_rate_pct": baseline_pass_rate,
        "current_pass_rate_pct": current_pass_rate,
        "diff_pct": diff,
        "regression_detected": regression,
    }


def format_summary_markdown(summary: dict[str, Any], comparison: dict[str, Any] | None = None) -> str:
    lines = [
        "# AI Data Analyst Agent - Evaluation Summary Report\n",
        f"- **Total Test Cases**: {summary['total_cases']}",
        f"- **Passed**: {summary['passed_cases']}",
        f"- **Pass Rate**: {summary['pass_rate_pct']}%\n",
    ]

    if comparison and comparison.get("has_baseline"):
        diff_str = f"+{comparison['diff_pct']}%" if comparison['diff_pct'] >= 0 else f"{comparison['diff_pct']}%"
        lines.append(f"- **Baseline Comparison**: Baseline={comparison['baseline_pass_rate_pct']}%, Delta={diff_str}")
        if comparison.get("regression_detected"):
            lines.append("⚠️ **REGRESSION DETECTED**: Pass rate dropped significantly!")
        lines.append("")

    lines.append("## Results by Category\n")
    lines.append("| Category | Total | Passed | Pass Rate |")
    lines.append("|---|---|---|---|")
    for cat, stats in summary.get("by_category", {}).items():
        rate = round(stats["passed"] / stats["total"] * 100.0, 1) if stats["total"] > 0 else 0.0
        lines.append(f"| {cat} | {stats['total']} | {stats['passed']} | {rate}% |")

    return "\n".join(lines)
