import math
import re

from analyst_agent.state import AnalysisStep, FinalReportData, GroundingViolationData

NUMERIC_LITERAL = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?%?")


def _violation(path: str, code: str, message: str) -> GroundingViolationData:
    return {"path": path, "code": code, "message": message}


def verify_grounding(
    report: FinalReportData, analysis_log: list[AnalysisStep]
) -> list[GroundingViolationData]:
    step_by_id = {step["step_id"]: step for step in analysis_log if step["success"]}
    violations: list[GroundingViolationData] = []
    for section in ("key_findings", "root_causes"):
        for index, finding in enumerate(report[section]):
            base = f"{section}[{index}]"
            citations = finding["citation_step_ids"]
            if not citations:
                violations.append(
                    _violation(
                        f"{base}.citation_step_ids", "empty_citation", "Citation list is empty"
                    )
                )
            if len(citations) != len(set(citations)):
                violations.append(
                    _violation(
                        f"{base}.citation_step_ids",
                        "duplicate_citation",
                        "Citation IDs must be unique",
                    )
                )
            invalid = [step_id for step_id in citations if step_id not in step_by_id]
            if invalid:
                violations.append(
                    _violation(
                        f"{base}.citation_step_ids",
                        "invalid_citation",
                        f"Unknown or failed step IDs: {', '.join(invalid)}",
                    )
                )
            numeric_claims = finding["numeric_claims"]
            if NUMERIC_LITERAL.search(finding["claim"]) and not numeric_claims:
                violations.append(
                    _violation(
                        f"{base}.numeric_claims",
                        "unregistered_numeric_literal",
                        "Claim contains numeric text but declares no numeric claims",
                    )
                )
            for claim_index, numeric in enumerate(numeric_claims):
                path = f"{base}.numeric_claims[{claim_index}]"
                step_id = numeric["citation_step_id"]
                if step_id not in citations:
                    violations.append(
                        _violation(
                            path,
                            "numeric_citation_mismatch",
                            "Numeric claim step is not cited by its finding",
                        )
                    )
                    continue
                step = step_by_id.get(step_id)
                if step is None:
                    violations.append(
                        _violation(
                            path,
                            "invalid_numeric_citation",
                            "Numeric claim references an unknown or failed step",
                        )
                    )
                    continue
                actual = step["metrics"].get(numeric["metric_name"])
                if actual is None:
                    violations.append(
                        _violation(
                            path,
                            "missing_metric",
                            f"Metric does not exist: {numeric['metric_name']}",
                        )
                    )
                    continue
                claimed = numeric["claimed_value"]
                if not math.isfinite(actual) or not math.isfinite(claimed):
                    violations.append(
                        _violation(path, "non_finite_metric", "Metric values must be finite")
                    )
                    continue
                tolerance = max(abs(actual) * numeric["tolerance_pct"] / 100, 1e-9)
                if abs(actual - claimed) > tolerance:
                    violations.append(
                        _violation(
                            path,
                            "numeric_mismatch",
                            f"Claimed {claimed} does not match actual {actual}",
                        )
                    )
    return violations
