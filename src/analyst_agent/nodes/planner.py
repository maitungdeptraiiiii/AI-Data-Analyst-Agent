from analyst_agent.context import format_clarification_context
from analyst_agent.llm import create_chat_model
from analyst_agent.schemas import PlannerOutput
from analyst_agent.state import AgentState

SYSTEM_PROMPT = """You are the planner for a data analysis agent.
Classify the user's request and, when ready, produce a short ordered analysis plan.
The executor runs each step with read-only SQL or sandboxed Python, whichever fits — a tool
router picks automatically based on keywords in the step text. The dataset has not been inspected
yet, so describe each plan step as an analytical GOAL in plain language (e.g. "Calculate monthly
revenue for the last 6 months", "Break down last month's revenue by region and product") —
never reference specific column or table names, since you don't know them yet. The executor sees
the real schema later and translates each goal into code.

Always write plan steps in English, even when the user's request is in another language: plan
steps are internal routing labels (the tool router matches English keywords like "correlation" or
"outlier" against them), never shown to the user directly. The final report is still written in
the user's own language by a later step — writing plan steps in English does not affect that.

Default to `ready` for any request about trends, comparisons, or breakdowns in the dataset, even
if the user did not specify exact dimensions or a comparison baseline. Fill in reasonable
defaults yourself instead of asking:
- No comparison period given -> compare against the immediately preceding period.
- No breakdown dimension given -> break down by every plausible categorical dimension a typical
  sales/business dataset would have (e.g. region, product, channel) as separate plan steps.
- No metric given -> assume the most obvious numeric measure implied by the request (e.g.
  "revenue" or "doanh thu" -> a revenue/amount-like column).

Only use need_clarification when the request is genuinely ambiguous in a way no reasonable
default resolves (e.g. it names a metric or entity that could refer to several unrelated things).
Use off_topic when the request is not about analyzing the supplied dataset.
Use ready only with a non-empty plan.
"""


def create_plan(state: AgentState) -> dict[str, object]:
    model = create_chat_model("planner").with_structured_output(PlannerOutput)
    from analyst_agent.memory.retriever import format_memory_context, retrieve_relevant_memory

    memories = retrieve_relevant_memory(state["dataset_path"])
    memory_context = format_memory_context(memories)

    human_prompt = (
        f"Dataset: {state['dataset_path']}\nRequest: {state['question']}\n\n"
        f"{format_clarification_context(state['clarification_history'])}\n\n"
        f"{memory_context}"
    )

    result = model.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", human_prompt.strip()),
        ]
    )
    assert isinstance(result, PlannerOutput)

    message: str | None = None
    if result.status == "need_clarification":
        message = result.clarification_question or "Please clarify the analysis request."
    elif result.status == "off_topic":
        message = "This request is outside the scope of dataset analysis."
    elif not result.plan:
        message = "The planner could not produce an executable analysis plan."

    return {
        "planner_status": result.status,
        "planner_message": message,
        "clarification_question": (
            result.clarification_question if result.status == "need_clarification" else None
        ),
        "plan": result.plan,
        "current_step": 0,
    }
