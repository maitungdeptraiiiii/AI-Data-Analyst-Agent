from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PlannerOutput(BaseModel):
    status: Literal["ready", "need_clarification", "off_topic"]
    clarification_question: str | None = None
    plan: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_payload(self) -> "PlannerOutput":
        if self.status == "ready" and not self.plan:
            raise ValueError("ready status requires a non-empty plan")
        if self.status == "need_clarification" and not self.clarification_question:
            raise ValueError("need_clarification status requires a question")
        if self.status != "ready" and self.plan:
            raise ValueError("only ready status may contain a plan")
        return self


class SQLGenerationOutput(BaseModel):
    sql: str = Field(description="A single read-only PostgreSQL SELECT or WITH query")
    purpose: str


class SQLFixOutput(BaseModel):
    diagnosis: str
    changes: list[str] = Field(default_factory=list)
    sql: str = Field(description="Corrected single read-only PostgreSQL SELECT or WITH query")


class PythonGenerationOutput(BaseModel):
    purpose: str
    code: str


class PythonFixOutput(BaseModel):
    diagnosis: str
    changes: list[str] = Field(default_factory=list)
    code: str


class CriticOutput(BaseModel):
    verdict: Literal["pass", "retry"]
    reason: str
    missing: list[str] = Field(default_factory=list)


class ReplanOutput(BaseModel):
    rationale: str
    additional_plan: list[str] = Field(default_factory=list, max_length=3)


class ChartSpec(BaseModel):
    title: str
    chart_type: Literal["bar", "line", "scatter"]
    source_step_id: str
    x_column: str
    y_column: str
    series_column: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    description: str


class ChartPlanOutput(BaseModel):
    should_create: bool
    reason: str
    chart: ChartSpec | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "ChartPlanOutput":
        if self.should_create != (self.chart is not None):
            raise ValueError("chart must be present exactly when should_create is true")
        return self


class Finding(BaseModel):
    claim: str
    supporting_step_ids: list[str] = Field(default_factory=list)


class FinalReport(BaseModel):
    summary: str
    key_findings: list[Finding] = Field(default_factory=list)
    root_causes: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    chart_paths: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    limitations: list[str] = Field(default_factory=list)
