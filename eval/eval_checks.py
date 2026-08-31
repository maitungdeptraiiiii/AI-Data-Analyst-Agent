from typing import Any

from analyst_agent.grounding import verify_grounding
from analyst_agent.state import AgentState, FinalReportData


def check_all_citations_valid(
    report: FinalReportData | None, state: AgentState
) -> tuple[bool, str]:
    if report is None:
        return False, "Report is missing"
    violations = verify_grounding(report, state.get("analysis_log", []))
    citation_violations = [v for v in violations if "citation" in v["code"]]
    if citation_violations:
        return False, f"Citation violations found: {citation_violations}"
    return True, "All citations valid"


def check_all_numeric_claims_match(
    report: FinalReportData | None, state: AgentState
) -> tuple[bool, str]:
    if report is None:
        return False, "Report is missing"
    violations = verify_grounding(report, state.get("analysis_log", []))
    numeric_violations = [
        v for v in violations if v["code"] in ("numeric_mismatch", "missing_metric")
    ]
    if numeric_violations:
        return False, f"Numeric claim mismatches found: {numeric_violations}"
    return True, "All numeric claims match"


def check_no_blocked_tool_calls(state: AgentState) -> tuple[bool, str]:
    for step in state.get("analysis_log", []):
        for attempt in step.get("attempts", []):
            if attempt.get("error_category") in ("blocked_sql", "blocked_python"):
                return False, f"Blocked policy violation in step {step['step_id']}"
    return True, "No blocked tool calls"


def check_confidence_not_low(report: FinalReportData | None) -> tuple[bool, str]:
    if report is None:
        return False, "Report is missing"
    if report.get("confidence") == "low":
        return False, "Report confidence is low"
    return True, f"Report confidence is {report.get('confidence')}"


def check_min_findings(report: FinalReportData | None, min_count: int = 1) -> tuple[bool, str]:
    if report is None:
        return False, "Report is missing"
    count = len(report.get("key_findings", []))
    if count < min_count:
        return False, f"Expected at least {min_count} findings, found {count}"
    return True, f"Found {count} findings"


def check_min_root_causes(report: FinalReportData | None, min_count: int = 1) -> tuple[bool, str]:
    if report is None:
        return False, "Report is missing"
    count = len(report.get("root_causes", []))
    if count < min_count:
        return False, f"Expected at least {min_count} root causes, found {count}"
    return True, f"Found {count} root causes"


def check_has_recommendations(report: FinalReportData | None) -> tuple[bool, str]:
    if report is None:
        return False, "Report is missing"
    count = len(report.get("recommendations", []))
    if count == 0:
        return False, "No recommendations provided"
    return True, f"Found {count} recommendations"


def check_min_plan_steps(state: AgentState, min_steps: int = 1) -> tuple[bool, str]:
    steps = len(state.get("plan", []))
    if steps < min_steps:
        return False, f"Expected at least {min_steps} plan steps, got {steps}"
    return True, f"Plan contains {steps} steps"


def check_no_sql_executed(state: AgentState) -> tuple[bool, str]:
    steps = state.get("analysis_log", [])
    if len(steps) > 0:
        return False, f"Expected no steps executed, but found {len(steps)}"
    return True, "No analysis steps were executed"


def check_expected_planner_status(state: AgentState, expected: str) -> tuple[bool, str]:
    actual = state.get("planner_status")
    if expected == "ready_or_need_clarification":
        if actual in ("ready", "need_clarification"):
            return True, f"Planner status is valid ({actual})"
        return False, f"Expected ready or need_clarification, got {actual}"
    if actual != expected:
        return False, f"Expected planner status '{expected}', got '{actual}'"
    return True, f"Planner status matched '{expected}'"


def evaluate_properties(properties: dict[str, Any], state: AgentState) -> dict[str, Any]:
    """Evaluate a dict of expected properties against the resulting agent state."""
    report = state.get("final_report") or state.get("draft_report")
    results: dict[str, dict[str, Any]] = {}
    all_passed = True

    for prop_name, expected_value in properties.items():
        passed = False
        message = ""

        if prop_name == "all_citations_valid" and expected_value is True:
            passed, message = check_all_citations_valid(report, state)
        elif prop_name == "all_numeric_claims_match" and expected_value is True:
            passed, message = check_all_numeric_claims_match(report, state)
        elif prop_name == "no_blocked_tool_calls" and expected_value is True:
            passed, message = check_no_blocked_tool_calls(state)
        elif prop_name == "confidence_not_low" and expected_value is True:
            passed, message = check_confidence_not_low(report)
        elif prop_name == "min_findings":
            passed, message = check_min_findings(report, int(expected_value))
        elif prop_name == "min_root_causes":
            passed, message = check_min_root_causes(report, int(expected_value))
        elif prop_name == "has_recommendations" and expected_value is True:
            passed, message = check_has_recommendations(report)
        elif prop_name == "min_plan_steps":
            passed, message = check_min_plan_steps(state, int(expected_value))
        elif prop_name == "no_sql_executed" and expected_value is True:
            passed, message = check_no_sql_executed(state)
        elif prop_name == "expected_planner_status":
            passed, message = check_expected_planner_status(state, str(expected_value))
        else:
            passed = True
            message = f"Property '{prop_name}' passed by default"

        results[prop_name] = {"passed": passed, "message": message}
        if not passed:
            all_passed = False

    return {
        "passed": all_passed,
        "property_results": results,
    }
