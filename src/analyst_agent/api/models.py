from typing import Any, Literal

from pydantic import BaseModel, Field


class StartAnalysisRequest(BaseModel):
    question: str
    dataset_name: str | None = None


class StartAnalysisResponse(BaseModel):
    job_id: str
    thread_id: str
    status: Literal["queued", "running", "completed", "interrupted", "failed"]
    message: str


class ResumeAnalysisRequest(BaseModel):
    answer: str


class ProgressEvent(BaseModel):
    event: Literal[
        "job_started",
        "node_start",
        "node_end",
        "clarification_needed",
        "chart_created",
        "completed",
        "error",
    ]
    node_name: str | None = None
    status: str
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class AnalysisResultResponse(BaseModel):
    job_id: str
    thread_id: str
    status: Literal["completed", "interrupted", "failed", "running"]
    question: str
    final_report: dict[str, Any] | None = None
    final_answer: str | None = None
    charts: list[dict[str, Any]] = Field(default_factory=list)
    analysis_log: list[dict[str, Any]] = Field(default_factory=list)
    node_metrics: list[dict[str, Any]] = Field(default_factory=list)
    clarification_question: str | None = None
    error: str | None = None


class DatasetSampleItem(BaseModel):
    id: str
    name: str
    path: str
    description: str
    rows: int
    columns: list[str]
