import os
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, Generation, LLMResult

from analyst_agent import llm, observability, state
from analyst_agent.nodes import executor_agent
from analyst_agent.observability import (
    TokenUsageTracker,
    build_node_metric,
    estimate_token_cost,
    setup_observability,
    trace_node_execution,
)


def test_estimate_token_cost_known_models() -> None:
    # gpt-4.1-mini: $0.15 / 1M in, $0.60 / 1M out
    # 10,000 in ($0.0015), 5,000 out ($0.0030) => $0.0045
    cost = estimate_token_cost("gpt-4.1-mini", 10_000, 5_000)
    assert cost == 0.0045

    # claude-3-5-sonnet: $3.00 / 1M in, $15.00 / 1M out
    # 1,000 in ($0.003), 1,000 out ($0.015) => $0.018
    cost_claude = estimate_token_cost("claude-3-5-sonnet", 1_000, 1_000)
    assert cost_claude == 0.018


def test_estimate_token_cost_fallback() -> None:
    cost = estimate_token_cost("unknown-custom-model", 100_000, 100_000)
    assert cost > 0


def test_token_usage_tracker_from_llm_output() -> None:
    tracker = TokenUsageTracker()
    result = LLMResult(
        generations=[[Generation(text="test output")]],
        llm_output={
            "token_usage": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
            },
            "model_name": "gpt-4.1-mini",
        },
    )
    tracker.on_llm_end(result)
    assert tracker.tokens_in == 120
    assert tracker.tokens_out == 45
    assert tracker.total_tokens == 165
    assert tracker.model_name == "gpt-4.1-mini"


def test_token_usage_tracker_from_message_metadata() -> None:
    tracker = TokenUsageTracker()
    msg = AIMessage(
        content="hello",
        usage_metadata={
            "input_tokens": 200,
            "output_tokens": 80,
            "total_tokens": 280,
        },
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(
        generations=[[gen]],
        llm_output={},
    )
    tracker.on_llm_end(result)
    assert tracker.tokens_in == 200
    assert tracker.tokens_out == 80
    assert tracker.total_tokens == 280


def test_trace_node_execution_records_duration_and_metrics() -> None:
    with trace_node_execution("test_node", model_role="planner") as tracker:
        tracker.tokens_in = 500
        tracker.tokens_out = 100
        tracker.total_tokens = 600

    metric = build_node_metric("test_node", 45.2, tracker, model_role="planner")
    assert metric["node_name"] == "test_node"
    assert metric["tokens_in"] == 500
    assert metric["tokens_out"] == 100
    assert metric["total_tokens"] == 600
    assert metric["duration_ms"] == 45.2
    assert metric["estimated_cost_usd"] > 0
    assert metric["timestamp"] > 0


def test_setup_observability_langsmith(monkeypatch) -> None:
    class MockSettings:
        observability_backend = "langsmith"
        langsmith_api_key = MagicMock()
        langsmith_api_key.get_secret_value.return_value = "ls_test_key_123"
        langsmith_project = "test-project"

    monkeypatch.setattr(observability, "get_settings", lambda: MockSettings())
    setup_observability()

    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    assert os.environ.get("LANGCHAIN_API_KEY") == "ls_test_key_123"
    assert os.environ.get("LANGCHAIN_PROJECT") == "test-project"


def test_create_chat_model_attaches_callbacks(monkeypatch) -> None:
    tracker = TokenUsageTracker()
    model = llm.create_chat_model("planner", callbacks=[tracker])
    assert model is not None
    assert tracker in model.callbacks


def test_trace_id_propagated_in_executor_task(monkeypatch) -> None:
    published_tasks: list[tuple[str, state.ToolTaskData]] = []
    monkeypatch.setattr(
        executor_agent.streams,
        "publish_tool_task",
        lambda tool, task: published_tasks.append((tool, task)),
    )
    monkeypatch.setattr(
        executor_agent.streams,
        "await_tool_result",
        lambda corr_id, timeout: {
            "code": "SELECT 1",
            "purpose": "test",
            "result": {
                "success": True,
                "rows": [{"col": 1}],
                "metrics": {"col": 1.0},
                "error": None,
            },
        },
    )

    initial: state.ExecutorAgentState = {
        "task": {
            "run_id": "trace_run_12345",
            "step_id": "step_1",
            "instruction": "Calculate revenue",
            "dataset_summary": {
                "table_name": "analysis.dataset_test",
                "columns": {"revenue": "BIGINT"},
                "n_rows": 10,
                "null_summary": {"revenue": 0},
            },
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

    _ = executor_agent.dispatch_tool(initial)
    assert len(published_tasks) == 1
    tool, task = published_tasks[0]
    assert task["trace_id"] == "trace_run_12345"
    assert "trace_run_12345" in task["correlation_id"]
