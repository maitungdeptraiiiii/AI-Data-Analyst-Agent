from analyst_agent.charts import create_chart
from analyst_agent.config import get_settings
from analyst_agent.schemas import ChartSpec
from analyst_agent.state import AgentState


def create_chart_node(state: AgentState) -> dict[str, object]:
    chart_plan = state["chart_plan"]
    if chart_plan is None:
        return {}
    try:
        artifact = create_chart(
            ChartSpec.model_validate(chart_plan),
            state["analysis_log"],
            get_settings().artifacts_dir,
            len(state["charts"]) + 1,
        )
        return {"charts": [*state["charts"], artifact], "chart_warning": None}
    except Exception as exc:
        warning = f"Chart creation was skipped: {exc}"
        return {
            "chart_warning": warning,
            "analysis_warnings": [*state["analysis_warnings"], warning],
        }
