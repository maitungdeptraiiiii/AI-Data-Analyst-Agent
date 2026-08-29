"""LLM-as-a-Judge Evaluation Module (G-Eval / MT-Bench style) for Analytical Reports."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class RubricCriterionScore(BaseModel):
    score: int = Field(ge=1, le=5, description="Score from 1 (poor) to 5 (excellent)")
    reasoning: str = Field(description="Explanation justifying the score")


class ReportJudgeEvaluation(BaseModel):
    relevance: RubricCriterionScore = Field(
        description="Does the report directly answer the user's specific analytical question?"
    )
    analytical_depth: RubricCriterionScore = Field(
        description="Does the report discover non-obvious root causes beyond surface stats?"
    )
    actionability: RubricCriterionScore = Field(
        description="Are the recommendations practical, concrete, and business-focused?"
    )
    faithfulness: RubricCriterionScore = Field(
        description="Are all claims strictly derived from query evidence without fabrication?"
    )
    presentation: RubricCriterionScore = Field(
        description="Is the report structure clear, professional, concise, and well-organized?"
    )
    overall_verdict: Literal["excellent", "acceptable", "needs_improvement", "unacceptable"]
    overall_score: float = Field(ge=1.0, le=5.0, description="Average across the 5 rubric criteria")
    summary_feedback: str = Field(description="High-level feedback and suggestions for improvement")


JUDGE_SYSTEM_PROMPT = """You are an expert Chief Data Officer and Senior Analytics Lead.
Evaluate the quality of an AI-generated data analysis report based on 5 strict criteria:

1. RELEVANCE (1-5):
   - 5: Perfectly tailored to the user's question, addressing every implied requirement.
   - 3: Answers the broad question but misses subtle constraints or nuances.
   - 1: Off-topic, answers a completely different question, or ignores the prompt.

2. ANALYTICAL DEPTH (1-5):
   - 5: Dissects root causes across multiple dimensions and explains WHY patterns occurred.
   - 3: Provides basic aggregations/trends but stops short of explaining root drivers.
   - 1: Superficial regurgitation of raw numbers with zero analytical value.

3. ACTIONABILITY (1-5):
   - 5: Provides specific, realistic, prioritized, and measurable business recommendations.
   - 3: Generic recommendations (e.g. "increase marketing") without specific focus.
   - 1: No recommendations, or recommendations that are nonsensical/unimplementable.

4. FAITHFULNESS & GROUNDING (1-5):
   - 5: Every single claim and number is strictly backed by evidence. Zero hallucinations.
   - 3: Mostly supported, but includes 1-2 minor unwarranted speculations.
   - 1: Major fabricated numbers or contradictory claims not found in the evidence.

5. PRESENTATION & STRUCTURE (1-5):
   - 5: Executive-ready formatting, concise bullets, clear citations, professional tone.
   - 3: Readable but verbose, clunky, or poorly structured.
   - 1: Incoherent, messy, or broken formatting.

Be strict, impartial, and constructive. Compute overall_score as the exact average."""


def evaluate_report_with_llm(
    question: str,
    evidence_log: list[dict[str, Any]],
    report_text: str,
    llm: Any | None = None,
) -> ReportJudgeEvaluation:
    """Evaluate an analytical report using LLM-as-a-Judge."""
    if llm is None:
        from analyst_agent.llm import create_chat_model

        llm = create_chat_model("critic").with_structured_output(ReportJudgeEvaluation)

    evidence_summary = [
        {
            "step_id": step.get("step_id"),
            "instruction": step.get("instruction"),
            "tool": step.get("tool"),
            "metrics": step.get("metrics"),
            "rows": step.get("rows", [])[:5],
            "success": step.get("success"),
        }
        for step in evidence_log
        if step.get("success")
    ]

    human_prompt = f"""[USER QUESTION]
{question}

[EXECUTION EVIDENCE LOG]
{evidence_summary}

[GENERATED ANALYTICAL REPORT]
{report_text}
"""

    result = llm.invoke(
        [
            ("system", JUDGE_SYSTEM_PROMPT),
            ("human", human_prompt),
        ]
    )

    if isinstance(result, ReportJudgeEvaluation):
        return result

    # Fallback / mock evaluation if model returns dict
    if isinstance(result, dict):
        return ReportJudgeEvaluation(**result)

    raise TypeError(f"Unexpected judge output type: {type(result)}")


def mock_judge_evaluation(
    question: str, report_text: str, is_valid: bool = True
) -> ReportJudgeEvaluation:
    """Fast deterministic mock for CI/CD environments without API keys."""
    base_score = 5 if is_valid else 2
    verdict: Literal["excellent", "acceptable", "needs_improvement", "unacceptable"] = (
        "excellent" if is_valid else "needs_improvement"
    )
    return ReportJudgeEvaluation(
        relevance=RubricCriterionScore(
            score=base_score,
            reasoning="Directly addresses the requested sales and revenue breakdown.",
        ),
        analytical_depth=RubricCriterionScore(
            score=base_score,
            reasoning="Identified specific product categories driving quarterly shifts.",
        ),
        actionability=RubricCriterionScore(
            score=base_score,
            reasoning="Clear recommendations with specific regional resource allocation.",
        ),
        faithfulness=RubricCriterionScore(
            score=base_score,
            reasoning="All cited numbers match SQL step metrics within 1% tolerance.",
        ),
        presentation=RubricCriterionScore(
            score=base_score,
            reasoning="Structured format with executive summary and clear bullet points.",
        ),
        overall_verdict=verdict,
        overall_score=float(base_score),
        summary_feedback="Report meets production quality standards with strong grounding.",
    )
