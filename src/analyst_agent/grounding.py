import math
import re

from analyst_agent.state import AnalysisStep, FinalReportData, GroundingViolationData

NUMERIC_LITERAL = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?%?")


def _violation(path: str, code: str, message: str) -> GroundingViolationData:
    return {"path": path, "code": code, "message": message}


RANK_PATTERNS: list[tuple[re.Pattern[str], int, bool, str]] = [
    (re.compile(r"\b(?:first|1st|highest|top|most)\b", re.IGNORECASE), 1, False, "first/highest"),
    (re.compile(r"\b(?:second|2nd)\b", re.IGNORECASE), 2, False, "second"),
    (re.compile(r"\b(?:third|3rd)\b", re.IGNORECASE), 3, False, "third"),
    (re.compile(r"\b(?:fourth|4th)\b", re.IGNORECASE), 4, False, "fourth"),
    (re.compile(r"\b(?:fifth|5th)\b", re.IGNORECASE), 5, False, "fifth"),
    (re.compile(r"\b(?:lowest|bottom|least|last)\b", re.IGNORECASE), 1, True, "lowest/bottom"),
]


def _check_ranking_grounding(
    finding_claim: str,
    citations: list[str],
    step_by_id: dict[str, AnalysisStep],
    base_path: str,
) -> list[GroundingViolationData]:
    violations: list[GroundingViolationData] = []
    claim_lower = finding_claim.lower()

    for step_id in citations:
        step = step_by_id.get(step_id)
        if not step or not step["rows"] or len(step["rows"]) < 2:
            continue

        rows = step["rows"]
        # Find numeric columns
        num_cols = [
            k
            for k, v in rows[0].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        if not num_cols:
            continue

        # Find string/category columns
        cat_cols = [k for k, v in rows[0].items() if isinstance(v, str)]
        if not cat_cols:
            continue

        # Determine target numeric column
        target_col = None
        for col in num_cols:
            col_normalized = col.replace("_", " ").lower()
            if col.lower() in claim_lower or col_normalized in claim_lower:
                target_col = col
                break
        if target_col is None and len(num_cols) == 1:
            target_col = num_cols[0]

        if not target_col:
            continue

        # Find target row in rows that best matches entities in the claim
        best_row = None
        best_score = 0
        for r in rows:
            score = sum(
                1
                for c in cat_cols
                if str(r.get(c, "")).strip() and str(r.get(c, "")).lower() in claim_lower
            )
            if score > best_score:
                best_score = score
                best_row = r

        if best_row is None or best_score == 0:
            continue

        # Check ranking assertions
        for pattern, expected_rank, is_ascending, label in RANK_PATTERNS:
            if pattern.search(claim_lower):
                try:
                    sorted_rows = sorted(
                        rows,
                        key=lambda x: float(str(x.get(target_col, 0) or 0)),
                        reverse=not is_ascending,
                    )
                except Exception:
                    continue

                actual_rank = None
                for idx, item in enumerate(sorted_rows, start=1):
                    if all(item.get(c) == best_row.get(c) for c in cat_cols):
                        actual_rank = idx
                        break

                if actual_rank is not None and actual_rank != expected_rank:
                    matched_entity = " / ".join(
                        str(best_row.get(c)) for c in cat_cols if best_row.get(c)
                    )
                    actual_val = best_row.get(target_col)
                    msg = (
                        f"Claimed rank '{label}' for '{matched_entity}' on '{target_col}', "
                        f"but actual rank in cited step '{step_id}' is {actual_rank} "
                        f"(value: {actual_val})."
                    )
                    violations.append(
                        _violation(
                            f"{base_path}.claim",
                            "ranking_contradiction",
                            msg,
                        )
                    )
    return violations


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
            # Check ranking / superlative grounding
            ranking_violations = _check_ranking_grounding(
                finding["claim"], citations, step_by_id, base
            )
            violations.extend(ranking_violations)
    return violations
