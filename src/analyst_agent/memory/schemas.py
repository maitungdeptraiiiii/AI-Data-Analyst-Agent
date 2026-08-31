from typing import Any

from pydantic import BaseModel, Field


class AnalysisRecord(BaseModel):
    id: str
    dataset_hash: str
    question: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)
    confidence: str = "high"
    created_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)
