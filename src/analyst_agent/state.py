from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages

from analyst_agent.errors import ExecutionError

ToolName = Literal["sql", "python"]


class DatasetInfo(TypedDict):
    table_name: str
    columns: dict[str, str]
    n_rows: int
    null_summary: dict[str, int]
    sample_rows: list[dict[str, object]]


class AnalysisAttempt(TypedDict):
    attempt: int
    tool: ToolName
    code: str
    success: bool
    error_category: str | None
    error_code: str | None
    error_message: str | None


class AnalysisStep(TypedDict):
    step_id: str
    instruction: str
    tool: ToolName
    code: str
    rows: list[dict[str, object]]
    metrics: dict[str, float]
    success: bool
    error: str | None
    attempts: list[AnalysisAttempt]


PlannerStatus = Literal["ready", "need_clarification", "off_topic"]
CriticVerdict = Literal["pass", "retry"]


class CriticReview(TypedDict):
    round: int
    verdict: CriticVerdict
    reason: str
    missing: list[str]


class ClarificationTurn(TypedDict):
    question: str
    answer: str


class ChartSpecData(TypedDict):
    title: str
    chart_type: Literal["bar", "line", "scatter"]
    source_step_id: str
    x_column: str
    y_column: str
    series_column: str | None
    x_label: str | None
    y_label: str | None
    description: str


class ChartArtifact(TypedDict):
    chart_id: str
    path: str
    title: str
    description: str
    chart_type: str
    source_step_id: str


class FindingData(TypedDict):
    claim: str
    supporting_step_ids: list[str]


class FinalReportData(TypedDict):
    summary: str
    key_findings: list[FindingData]
    root_causes: list[FindingData]
    recommendations: list[str]
    chart_paths: list[str]
    confidence: Literal["high", "medium", "low"]
    limitations: list[str]


class AgentState(TypedDict):
    messages: Annotated[list[object], add_messages]
    question: str
    dataset_path: str
    planner_status: PlannerStatus | None
    planner_message: str | None
    clarification_question: str | None
    clarification_history: list[ClarificationTurn]
    clarification_count: int
    max_clarifications: int
    dataset_info: DatasetInfo | None
    plan: list[str]
    current_step: int
    current_tool: ToolName | None
    current_code: str | None
    current_purpose: str | None
    current_rows: list[dict[str, object]]
    current_metrics: dict[str, float]
    current_error: ExecutionError | None
    current_attempts: list[AnalysisAttempt]
    execution_retry_count: int
    execution_max_retries: int
    critic_verdict: CriticVerdict | None
    critic_reason: str | None
    critic_missing: list[str]
    critic_retry_count: int
    critic_max_retries: int
    critic_history: list[CriticReview]
    analysis_warnings: list[str]
    analysis_log: list[AnalysisStep]
    chart_plan: ChartSpecData | None
    charts: list[ChartArtifact]
    chart_warning: str | None
    final_report: FinalReportData | None
    final_answer: str | None
