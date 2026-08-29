import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from analyst_agent.config import get_settings
from analyst_agent.llm import ModelRole
from analyst_agent.state import NodeMetricsData

logger = logging.getLogger(__name__)

# Price per million tokens ($/1M tokens) - (input_cost, output_cost)
MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4.1-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5": (5.00, 20.00),
    # Anthropic
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-haiku-4": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
}
DEFAULT_PRICING: tuple[float, float] = (1.00, 3.00)


def estimate_token_cost(model_name: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate estimated cost in USD for the given token usage."""
    pricing = MODEL_PRICING_PER_1M.get(model_name.lower())
    if pricing is None:
        for key, price in MODEL_PRICING_PER_1M.items():
            if key in model_name.lower():
                pricing = price
                break
    if pricing is None:
        pricing = DEFAULT_PRICING

    input_rate, output_rate = pricing
    cost = (tokens_in * input_rate + tokens_out * output_rate) / 1_000_000.0
    return round(cost, 6)


class TokenUsageTracker(BaseCallbackHandler):
    """LangChain callback handler to capture token usage across LLM calls in a node."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens_in: int = 0
        self.tokens_out: int = 0
        self.total_tokens: int = 0
        self.model_name: str | None = None

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            if response.llm_output:
                usage = response.llm_output.get("token_usage") or response.llm_output.get("usage")
                if usage:
                    self.tokens_in += (
                        usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                    )
                    self.tokens_out += (
                        usage.get("completion_tokens") or usage.get("output_tokens") or 0
                    )
                    self.total_tokens += usage.get("total_tokens") or (
                        self.tokens_in + self.tokens_out
                    )
                model = response.llm_output.get("model_name") or response.llm_output.get("model")
                if model:
                    self.model_name = str(model)

            if not self.total_tokens and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        msg = getattr(gen, "message", None)
                        if msg and hasattr(msg, "usage_metadata") and msg.usage_metadata:
                            meta = msg.usage_metadata
                            self.tokens_in += meta.get("input_tokens", 0)
                            self.tokens_out += meta.get("output_tokens", 0)
                            self.total_tokens += meta.get("total_tokens", 0)
        except Exception as exc:
            logger.debug("Failed to extract token usage: %s", exc)


def setup_observability() -> None:
    """Initialize LangSmith / Tracing if configured in settings."""
    settings = get_settings()
    if settings.observability_backend == "langsmith" and settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key.get_secret_value()
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        logger.info("LangSmith tracing enabled for project: %s", settings.langsmith_project)


@contextmanager
def trace_node_execution(
    node_name: str,
    model_role: ModelRole | None = None,
) -> Iterator[TokenUsageTracker]:
    """Context manager to measure node execution time and token usage."""
    tracker = TokenUsageTracker()
    start_time = time.monotonic()
    try:
        yield tracker
    finally:
        duration_ms = round((time.monotonic() - start_time) * 1000.0, 2)
        settings = get_settings()
        model_name = tracker.model_name
        if not model_name and model_role:
            model_name = getattr(settings, f"{model_role}_model", None)

        cost = estimate_token_cost(
            model_name or "default",
            tracker.tokens_in,
            tracker.tokens_out,
        )
        logger.info(
            "Node '%s' finished in %.2fms (tokens_in=%d, tokens_out=%d, cost=$%.6f)",
            node_name,
            duration_ms,
            tracker.tokens_in,
            tracker.tokens_out,
            cost,
        )


def build_node_metric(
    node_name: str,
    duration_ms: float,
    tracker: TokenUsageTracker,
    model_role: ModelRole | None = None,
) -> NodeMetricsData:
    """Construct a NodeMetricsData entry for state aggregation."""
    settings = get_settings()
    model_name = tracker.model_name
    if not model_name and model_role:
        model_name = getattr(settings, f"{model_role}_model", None)

    cost = estimate_token_cost(
        model_name or "default",
        tracker.tokens_in,
        tracker.tokens_out,
    )
    return {
        "node_name": node_name,
        "duration_ms": duration_ms,
        "tokens_in": tracker.tokens_in,
        "tokens_out": tracker.tokens_out,
        "total_tokens": tracker.total_tokens or (tracker.tokens_in + tracker.tokens_out),
        "model": model_name,
        "estimated_cost_usd": cost,
        "timestamp": time.time(),
    }
