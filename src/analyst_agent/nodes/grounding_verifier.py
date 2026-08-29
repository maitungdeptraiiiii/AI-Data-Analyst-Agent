import re
from typing import cast

from analyst_agent.grounding import verify_grounding
from analyst_agent.nodes.reporter import format_report
from analyst_agent.schemas import FinalReport
from analyst_agent.state import AgentState, FinalReportData


def verify_report(state: AgentState) -> dict[str, object]:
    draft = state["draft_report"]
    if draft is None:
        raise ValueError("Grounding verifier requires a draft report")
    violations = verify_grounding(draft, state["analysis_log"])
    return {
        "grounding_violations": violations,
        "grounding_status": "invalid" if violations else "valid",
    }


def prepare_grounding_retry(state: AgentState) -> dict[str, object]:
    return {"grounding_retry_count": state["grounding_retry_count"] + 1}


def sanitize_report(state: AgentState) -> dict[str, object]:
    draft = state["draft_report"]
    if draft is None:
        raise ValueError("Sanitizer requires a draft report")
    invalid: dict[str, set[int]] = {"key_findings": set(), "root_causes": set()}
    for violation in state["grounding_violations"]:
        match = re.match(r"(key_findings|root_causes)\[(\d+)\]", violation["path"])
        if match:
            invalid[match.group(1)].add(int(match.group(2)))
    report = FinalReport.model_validate(draft)
    limitation = (
        "Some findings were removed because their citations or numeric values "
        "could not be verified."
    )
    sanitized = report.model_copy(
        update={
            "key_findings": [
                item
                for i, item in enumerate(report.key_findings)
                if i not in invalid["key_findings"]
            ],
            "root_causes": [
                item for i, item in enumerate(report.root_causes) if i not in invalid["root_causes"]
            ],
            "confidence": "low",
            "limitations": list(dict.fromkeys([*report.limitations, limitation])),
        }
    )
    warning = "Grounding retry budget exhausted; invalid findings were removed."
    return {
        "final_report": cast(FinalReportData, sanitized.model_dump()),
        "analysis_warnings": [*state["analysis_warnings"], warning],
    }


def finalize_report(state: AgentState) -> dict[str, object]:
    report_data = state["final_report"] or state["draft_report"]
    if report_data is None:
        raise ValueError("Finalizer requires a verified or sanitized report")
    report = FinalReport.model_validate(report_data)
    return {
        "final_report": report_data,
        "final_answer": format_report(report),
    }
