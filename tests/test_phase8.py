from typing import cast

from psycopg import errors

from analyst_agent.cli import initial_state
from analyst_agent.graph import build_graph
from analyst_agent.nodes import executor_agent
from analyst_agent.nodes.tool_agents import python_agent, sql_agent
from analyst_agent.nodes.tool_router import select_tool
from analyst_agent.schemas import SQLFixOutput
from analyst_agent.state import (
    AgentState,
    AnalysisAttempt,
    AnalysisStep,
    DatasetSummaryData,
    ExecutorAgentState,
    ExecutorResultData,
    ToolAgentState,
    ToolResultData,
    ToolTaskData,
)


def dataset_summary(**updates: object) -> DatasetSummaryData:
    summary: DatasetSummaryData = {
        "table_name": "analysis.dataset_test",
        "columns": {"date": "timestamp with time zone", "revenue": "bigint"},
        "n_rows": 3,
        "null_summary": {"date": 0, "revenue": 0},
    }
    summary.update(cast(dict, updates))
    return summary


def tool_task(**updates: object) -> ToolTaskData:
    task: ToolTaskData = {
        "correlation_id": "step_1:0",
        "instruction": "Calculate monthly revenue",
        "dataset_summary": dataset_summary(),
        "attempt": 1,
        "previous_code": None,
        "previous_purpose": None,
        "previous_error": None,
    }
    task.update(cast(dict, updates))
    return task


def executor_agent_state(**updates: object) -> ExecutorAgentState:
    state: ExecutorAgentState = {
        "task": {
            "step_id": "step_1",
            "instruction": "Calculate monthly revenue",
            "dataset_summary": dataset_summary(),
        },
        "tool_choice": "sql",
        "code": None,
        "purpose": None,
        "tool_result": None,
        "attempts": [],
        "local_retry_count": 0,
        "local_max_retries": 2,
        "wait_timeout_sec": 5.0,
        "result": None,
    }
    state.update(cast(dict, updates))
    return state


def phase8_state(**updates: object) -> AgentState:
    state = initial_state("Analyze revenue", "data/sample_sales.csv")
    state.update(  # type: ignore[typeddict-item]
        {
            "planner_status": "ready",
            "dataset_info": {**dataset_summary(), "sample_rows": []},
            "plan": ["Calculate monthly revenue"],
            **updates,
        }
    )
    return state


def test_router_defaults_sql_and_selects_python_for_correlation() -> None:
    assert select_tool("Calculate revenue by month", dataset_summary()) == "sql"
    correlation = "Calculate correlation between price and units"
    assert select_tool(correlation, dataset_summary()) == "python"


def test_router_forces_sql_for_large_dataset() -> None:
    huge = dataset_summary(n_rows=100_001)
    assert select_tool("Calculate correlation", huge) == "sql"


def test_sql_agent_run_classifies_failed_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_sql(_query: str) -> list[dict[str, object]]:
        raise errors.UndefinedColumn("column missing does not exist")

    monkeypatch.setattr(sql_agent, "execute_readonly_sql", fail_sql)
    state: ToolAgentState = {
        "task": tool_task(),
        "generated_code": "SELECT missing FROM analysis.dataset_test",
        "purpose": "Calculate monthly revenue",
        "result": None,
    }
    update = sql_agent.run(state)
    result = cast(ToolResultData, update["result"])
    assert result["success"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == "42703"


def test_union_order_by_syntax_error_is_retryable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    failed_sql = """SELECT month, revenue FROM monthly
UNION ALL
SELECT NULL, SUM(revenue) FROM monthly
ORDER BY date_trunc('month', month)"""

    def fail_union_order_by(_query: str) -> list[dict[str, object]]:
        raise errors.SyntaxError(
            "invalid UNION/INTERSECT/EXCEPT ORDER BY clause: "
            "Only result column names can be used, not expressions or functions"
        )

    monkeypatch.setattr(sql_agent, "execute_readonly_sql", fail_union_order_by)
    state: ToolAgentState = {
        "task": tool_task(instruction="Compare monthly revenue and include a summary"),
        "generated_code": failed_sql,
        "purpose": "Compare monthly revenue and include a summary",
        "result": None,
    }
    update = sql_agent.run(state)
    result = cast(ToolResultData, update["result"])
    assert result["error"] is not None
    assert result["error"]["code"] == "42601"

    executor_state = executor_agent_state(
        tool_result=result, local_retry_count=0, local_max_retries=2
    )
    assert executor_agent.route_after_dispatch(executor_state) == "retry"


def test_sql_agent_generate_repairs_failed_code_via_llm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    corrected_sql = """WITH combined AS (
    SELECT month, revenue FROM monthly
    UNION ALL
    SELECT NULL, SUM(revenue) FROM monthly
)
SELECT * FROM combined ORDER BY month"""
    captured_messages: list[object] = []

    class FakeStructuredModel:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            assert schema is SQLFixOutput
            return self

        def invoke(self, messages):  # type: ignore[no-untyped-def]
            captured_messages.extend(messages)
            return SQLFixOutput(
                diagnosis="ORDER BY after UNION uses an expression not present in the output",
                changes=["Wrapped the UNION in a CTE", "Ordered by the output column"],
                sql=corrected_sql,
            )

    monkeypatch.setattr(sql_agent, "create_chat_model", lambda role: FakeStructuredModel())
    state: ToolAgentState = {
        "task": tool_task(
            instruction="Compare monthly revenue and include a summary",
            previous_code="SELECT month FROM monthly UNION ALL SELECT NULL ORDER BY lower(month)",
            previous_purpose="Compare monthly revenue and include a summary",
            previous_error="invalid UNION/INTERSECT/EXCEPT ORDER BY clause",
        ),
        "generated_code": None,
        "purpose": None,
        "result": None,
    }

    update = sql_agent.generate(state)

    assert update["generated_code"] == corrected_sql
    assert update["purpose"] == "Compare monthly revenue and include a summary"
    assert "Compare monthly revenue and include a summary" in str(captured_messages)


def test_python_agent_run_returns_generated_metrics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sandbox_result: ToolResultData = {
        "success": True,
        "rows": [{"value": 10}],
        "metrics": {"outlier_count": 2.0},
        "error": None,
    }
    monkeypatch.setattr(python_agent, "execute_python_sandbox", lambda code, table: sandbox_result)
    state: ToolAgentState = {
        "task": tool_task(instruction="Detect outliers"),
        "generated_code": "metrics = {'n': 2}",
        "purpose": "Outlier analysis",
        "result": None,
    }
    update = python_agent.run(state)
    assert update["result"] == sandbox_result


def test_retryable_error_under_budget_routes_to_retry() -> None:
    tool_result: ToolResultData = {
        "success": False,
        "rows": [],
        "metrics": {},
        "error": {
            "category": "retryable_sql",
            "code": "42601",
            "message": "syntax error",
            "retryable": True,
        },
    }
    state = executor_agent_state(
        tool_result=tool_result, local_retry_count=0, local_max_retries=2
    )
    assert executor_agent.route_after_dispatch(state) == "retry"


def test_retry_cap_routes_to_finalize() -> None:
    tool_result: ToolResultData = {
        "success": False,
        "rows": [],
        "metrics": {},
        "error": {
            "category": "retryable_sql",
            "code": "42601",
            "message": "syntax error",
            "retryable": True,
        },
    }
    state = executor_agent_state(
        tool_result=tool_result, local_retry_count=2, local_max_retries=2
    )
    assert executor_agent.route_after_dispatch(state) == "finalize"


def test_blocked_error_routes_to_finalize_without_retry() -> None:
    tool_result: ToolResultData = {
        "success": False,
        "rows": [],
        "metrics": {},
        "error": {
            "category": "blocked_sql",
            "code": "25006",
            "message": "read-only transaction",
            "retryable": False,
        },
    }
    state = executor_agent_state(tool_result=tool_result)
    assert executor_agent.route_after_dispatch(state) == "finalize"


def test_executor_agent_finalize_preserves_attempts() -> None:
    attempt: AnalysisAttempt = {
        "attempt": 1,
        "tool": "sql",
        "code": "SELECT SUM(revenue) FROM analysis.dataset_test",
        "success": True,
        "error_category": None,
        "error_code": None,
        "error_message": None,
    }
    tool_result: ToolResultData = {
        "success": True,
        "rows": [{"sum": 100}],
        "metrics": {},
        "error": None,
    }
    state = executor_agent_state(
        code="SELECT SUM(revenue) FROM analysis.dataset_test",
        purpose="Calculate monthly revenue",
        tool_result=tool_result,
        attempts=[attempt],
    )
    update = executor_agent.finalize(state)
    result = update["result"]
    assert result["attempts"] == [attempt]
    assert result["success"] is True
    assert result["step_id"] == "step_1"


def test_orchestrator_assigns_step_id_and_preserves_critic_budget(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeExecutorAgentGraph:
        def invoke(self, initial: ExecutorAgentState) -> ExecutorAgentState:
            task = initial["task"]
            result: ExecutorResultData = {
                "step_id": task["step_id"],
                "success": True,
                "tool_used": "sql",
                "code": "SELECT SUM(revenue) FROM analysis.dataset_test",
                "purpose": "Additional evidence",
                "rows": [{"sum": 25_000}],
                "metrics": {},
                "error": None,
                "attempts": [],
            }
            return {**initial, "result": result}

    monkeypatch.setattr(
        executor_agent, "get_executor_agent_graph", lambda: FakeExecutorAgentGraph()
    )
    existing_step: AnalysisStep = {
        "step_id": "step_1",
        "instruction": "Calculate monthly revenue",
        "tool": "sql",
        "code": "SELECT date_trunc('month', date) FROM analysis.dataset_test",
        "rows": [],
        "metrics": {},
        "success": True,
        "error": None,
        "attempts": [],
    }
    state = phase8_state(analysis_log=[existing_step], critic_retry_count=1)

    update = executor_agent.run_executor_agent(state)

    log = cast(list[AnalysisStep], update["analysis_log"])
    assert log[-1]["step_id"] == "step_2"
    assert update["current_step"] == 1
    assert state["critic_retry_count"] == 1


def test_graph_wires_orchestrator_through_executor_agent() -> None:
    edges = {(edge.source, edge.target) for edge in build_graph().get_graph().edges}
    assert ("data_inspector", "run_executor_agent") in edges
    assert ("run_executor_agent", "run_executor_agent") in edges
    assert ("run_executor_agent", "critic") in edges
    assert ("replan", "run_executor_agent") in edges
