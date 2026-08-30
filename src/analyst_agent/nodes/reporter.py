import json
from typing import cast

from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from analyst_agent.context import format_clarification_context
from analyst_agent.llm import create_chat_model
from analyst_agent.schemas import FinalReport
from analyst_agent.state import AgentState, FinalReportData

SYSTEM_PROMPT = """Write a structured data analysis report using only successful analysis evidence
(from read-only SQL and/or sandboxed Python). Never infer findings from failed steps or errors.
Every finding and root cause must cite successful step IDs. Every number in a claim must declare a
numeric_claim using the exact metric name and step ID. A step's metrics come from its evidence rows:
a single-row result exposes each column directly (e.g. "revenue"); a breakdown result (one row per
category) exposes "{column}__{category}" per row (e.g. "revenue__2026_07"). Only cite metric names
that literally appear in that step's metrics object. Summary must not introduce new numbers or
causes. Recommendations are suggestions, not observed facts. Reply in the user's language.
When making comparative or ranking claims (e.g. 'ranks second', 'highest', 'lowest', 'top',
'bottom'), you MUST strictly inspect all rows in the cited step to verify the actual rank.
Never claim an entity ranks second if its value is the highest among all rows in the evidence.
Do not invent chart paths; application code supplies them after generation.
If the supplied chart list is non-empty, at least one chart was already generated: reference what
it shows in the summary or findings, and do not claim in limitations that no chart is available.
If the supplied chart list is empty, do not mention charts at all.
"""


def _deduplicate(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item.strip()))


def constrain_report(report: FinalReport, state: AgentState) -> FinalReport:
    successful = [step for step in state["analysis_log"] if step["success"]]
    failed = [step for step in state["analysis_log"] if not step["success"]]
    confidence = report.confidence
    if state["analysis_warnings"] or not successful:
        confidence = "low"
    elif failed and confidence == "high":
        confidence = "medium"
    return report.model_copy(
        update={
            "chart_paths": [chart["path"] for chart in state["charts"]],
            "confidence": confidence,
            "limitations": _deduplicate([*report.limitations, *state["analysis_warnings"]]),
        }
    )


def format_report(report: FinalReport) -> str:
    sections = [report.summary.strip()]
    if report.key_findings:
        sections.append(
            "Key findings:\n"
            + "\n".join(
                f"- {item.claim} [{', '.join(item.citation_step_ids)}]"
                for item in report.key_findings
            )
        )
    if report.root_causes:
        sections.append(
            "Root causes:\n"
            + "\n".join(
                f"- {item.claim} [{', '.join(item.citation_step_ids)}]"
                for item in report.root_causes
            )
        )
    if report.recommendations:
        sections.append(
            "Recommendations:\n" + "\n".join(f"- {item}" for item in report.recommendations)
        )
    if report.chart_paths:
        sections.append("Charts:\n" + "\n".join(f"- {path}" for path in report.chart_paths))
    if report.limitations:
        sections.append("Limitations:\n" + "\n".join(f"- {item}" for item in report.limitations))
    sections.append(f"Confidence: {report.confidence}")
    return "\n\n".join(sections)


def create_report(state: AgentState) -> dict[str, object]:
    if state["planner_status"] != "ready":
        report = FinalReport(
            summary=state["planner_message"] or "The request is not ready for dataset analysis.",
            key_findings=[],
            root_causes=[],
            recommendations=[],
            limitations=["No dataset analysis was executed for this request."],
            confidence="low",
            chart_paths=[],
        )
        return {
            "draft_report": cast(FinalReportData, report.model_dump()),
            "grounding_status": "pending",
        }

    evidence = [
        {
            "step_id": step["step_id"],
            "instruction": step["instruction"],
            "tool": step["tool"],
            "rows": step["rows"],
            "metrics": step["metrics"],
            "success": True,
        }
        for step in state["analysis_log"]
        if step["success"]
    ]
    failed_steps = [
        {"step_id": step["step_id"], "instruction": step["instruction"], "success": False}
        for step in state["analysis_log"]
        if not step["success"]
    ]
    # Path is intentionally omitted: constrain_report() fills chart_paths deterministically
    # afterward, so the LLM only needs enough to narrate the chart, not to reproduce its path.
    charts = [
        {
            "title": chart["title"],
            "description": chart["description"],
            "chart_type": chart["chart_type"],
        }
        for chart in state["charts"]
    ]
    base_messages = [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            f"Request:\n{state['question']}\n\n"
            f"{format_clarification_context(state['clarification_history'])}\n\n"
            "Successful evidence:\n"
            f"{json.dumps(evidence, default=str, ensure_ascii=False)}\n\n"
            "Failed steps (debug details omitted):\n"
            f"{json.dumps(failed_steps, ensure_ascii=False)}\n\n"
            f"Critic history:\n{json.dumps(state['critic_history'], ensure_ascii=False)}\n\n"
            f"Warnings:\n{json.dumps(state['analysis_warnings'], ensure_ascii=False)}\n\n"
            f"Charts already generated (paths supplied separately):\n"
            f"{json.dumps(charts, ensure_ascii=False)}\n\n"
            f"Previous draft:\n{json.dumps(state['draft_report'], ensure_ascii=False)}\n\n"
            "Deterministic grounding violations:\n"
            f"{json.dumps(state['grounding_violations'], ensure_ascii=False)}",
        ),
    ]
    model = create_chat_model("reporter").with_structured_output(FinalReport)
    result = None
    messages = list(base_messages)
    for attempt in range(2):
        try:
            candidate = model.invoke(messages)
            assert isinstance(candidate, FinalReport)
            result = candidate
            break
        except (ValidationError, OutputParserException) as exc:
            if attempt == 1:
                raise
            messages.append(
                (
                    "human",
                    "Your structured report violated its schema. Return a complete corrected "
                    f"report. Validation error: {str(exc)[:1000]}",
                )
            )
    assert result is not None
    constrained = constrain_report(result, state)
    report_data = cast(FinalReportData, constrained.model_dump())
    return {
        "draft_report": report_data,
        "grounding_status": "pending",
    }
