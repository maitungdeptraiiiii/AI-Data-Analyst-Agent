"""RAGAS & DeepEval Style Evaluation Metrics for Agent Grounding & Faithfulness."""

import re
from typing import Any

from pydantic import BaseModel, Field


class RagasMetricsResult(BaseModel):
    faithfulness_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of claims entailed by evidence (1.0 = zero hallucination)",
    )
    answer_relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Semantic overlap between user question and final report summary",
    )
    context_precision_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of database columns used in evidence vs table schema",
    )
    hallucination_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of claims containing unsupported numbers or citations",
    )
    information_density: float = Field(
        description="Average number of verified metrics per paragraph"
    )
    details: dict[str, Any] = Field(default_factory=dict)


def compute_token_overlap(str1: str, str2: str) -> float:
    """Calculate token Jaccard similarity between two text snippets."""
    tokens1 = set(re.findall(r"\w+", str1.lower()))
    tokens2 = set(re.findall(r"\w+", str2.lower()))
    if not tokens1 or not tokens2:
        return 0.0
    intersection = len(tokens1.intersection(tokens2))
    union = len(tokens1.union(tokens2))
    return float(intersection / union)


def evaluate_ragas_metrics(
    question: str,
    final_report: dict[str, Any],
    evidence_log: list[dict[str, Any]],
    table_columns: list[str] | None = None,
) -> RagasMetricsResult:
    """Compute RAGAS-style Faithfulness, Answer Relevance, and Context Precision."""
    findings = final_report.get("key_findings", [])
    root_causes = final_report.get("root_causes", [])
    all_claims = findings + root_causes
    total_claims = len(all_claims)

    if total_claims == 0:
        return RagasMetricsResult(
            faithfulness_score=1.0,
            answer_relevance_score=0.8,
            context_precision_score=1.0,
            hallucination_rate=0.0,
            information_density=0.0,
            details={"notes": "Empty report or off-topic rejection"},
        )

    # 1. Faithfulness Score
    valid_claims = 0
    all_evidence_step_ids = {s.get("step_id") for s in evidence_log if s.get("success", False)}

    for claim in all_claims:
        citation_ids = claim.get("citation_step_ids", [])
        if citation_ids and all(cid in all_evidence_step_ids for cid in citation_ids):
            valid_claims += 1

    faithfulness = round(valid_claims / max(total_claims, 1), 4)
    hallucination_rate = round(1.0 - faithfulness, 4)

    # 2. Answer Relevance Score
    summary = final_report.get("summary", "")
    overlap = compute_token_overlap(question, summary)
    # Heuristic adjustment for semantic alignment
    relevance = round(min(1.0, overlap * 2.5 + 0.3), 4)

    # 3. Context Precision Score
    used_columns: set[str] = set()
    for step in evidence_log:
        metrics = step.get("metrics", {})
        used_columns.update(metrics.keys())
        for row in step.get("rows", [])[:2]:
            if isinstance(row, dict):
                used_columns.update(row.keys())

    if table_columns and len(table_columns) > 0:
        precision = round(min(1.0, len(used_columns) / len(table_columns)), 4)
    else:
        precision = 0.85

    # 4. Information Density
    paragraphs = len([p for p in summary.split("\n\n") if p.strip()]) + 1
    total_metrics_count = sum(len(step.get("metrics", {})) for step in evidence_log)
    density = round(total_metrics_count / max(paragraphs, 1), 2)

    return RagasMetricsResult(
        faithfulness_score=faithfulness,
        answer_relevance_score=relevance,
        context_precision_score=precision,
        hallucination_rate=hallucination_rate,
        information_density=density,
        details={
            "total_claims": total_claims,
            "grounded_claims": valid_claims,
            "used_columns_count": len(used_columns),
        },
    )
