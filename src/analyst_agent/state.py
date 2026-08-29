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


class DatasetSummaryData(TypedDict):
    """`DatasetInfo` without `sample_rows` — schema/dtype only, sent across agent boundaries."""

    table_name: str
    columns: dict[str, str]
    n_rows: int
    null_summary: dict[str, int]


class ToolResultData(TypedDict):
    success: bool
    rows: list[dict[str, object]]
    metrics: dict[str, float]
    error: ExecutionError | None


class ExecutorTaskData(TypedDict):
    """Orchestrator -> Executor Agent handoff (mục 6.3.1)."""

    run_id: str
    step_id: str
    instruction: str
    dataset_summary: DatasetSummaryData


class ExecutorResultData(TypedDict):
    """Executor Agent -> Orchestrator handoff (mục 6.3.1)."""

    step_id: str
    success: bool
    tool_used: ToolName
    code: str
    purpose: str
    rows: list[dict[str, object]]
    metrics: dict[str, float]
    error: str | None
    attempts: list[AnalysisAttempt]


class ToolTaskData(TypedDict):
    """Executor Agent -> Tool Agent handoff (mục 6.3.1/6.3.4b); a `tasks:{tool}` stream entry."""

    correlation_id: str
    instruction: str
    dataset_summary: DatasetSummaryData
    attempt: int
    previous_code: str | None
    previous_purpose: str | None
    previous_error: str | None


class ToolResultMessage(TypedDict):
    """Payload a Tool Agent worker publishes to `results:{correlation_id}` (mục 6.3.4b) — the
    Tool Agent's generated code/purpose only exist in the worker process, so they ride along
    with the ToolResult itself instead of being reconstructed by the Executor Agent."""

    code: str
    purpose: str
    result: ToolResultData


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


class NumericClaimData(TypedDict):
    citation_step_id: str
    metric_name: str
    claimed_value: float
    tolerance_pct: float


class FindingData(TypedDict):
    claim: str
    citation_step_ids: list[str]
    numeric_claims: list[NumericClaimData]


class FinalReportData(TypedDict):
    summary: str
    key_findings: list[FindingData]
    root_causes: list[FindingData]
    recommendations: list[str]
    chart_paths: list[str]
    confidence: Literal["high", "medium", "low"]
    limitations: list[str]


class GroundingViolationData(TypedDict):
    path: str
    code: str
    message: str


class AgentState(TypedDict):
    messages: Annotated[list[object], add_messages]
    run_id: str
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
    draft_report: FinalReportData | None
    grounding_violations: list[GroundingViolationData]
    grounding_retry_count: int
    grounding_max_retries: int
    grounding_status: Literal["pending", "valid", "invalid"] | None
    final_answer: str | None


class ToolAgentState(TypedDict):
    """State of the Tool Agent subgraph (mục 6.3.3) — 1 tool per agent, narrow scope."""

    task: ToolTaskData
    generated_code: str | None
    purpose: str | None
    result: ToolResultData | None


class ExecutorAgentState(TypedDict):
    """State of the Executor Agent subgraph (mục 6.3.2)."""

    task: ExecutorTaskData
    tool_choice: ToolName | None
    code: str | None
    purpose: str | None
    tool_result: ToolResultData | None
    attempts: list[AnalysisAttempt]
    local_retry_count: int
    local_max_retries: int
    wait_timeout_sec: float
    result: ExecutorResultData | None
