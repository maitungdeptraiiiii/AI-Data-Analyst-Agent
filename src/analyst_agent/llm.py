from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from analyst_agent.config import get_settings

ModelRole = Literal["planner", "executor", "critic", "reporter"]


def create_chat_model(role: ModelRole, callbacks: list[Any] | None = None) -> BaseChatModel:
    """Create the configured provider without leaking provider logic into graph nodes."""
    settings = get_settings()
    model_name = getattr(settings, f"{role}_model")

    if settings.llm_provider == "openai":
        assert settings.openai_api_key is not None
        return ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
            callbacks=callbacks,
        )

    assert settings.anthropic_api_key is not None
    return ChatAnthropic(
        model_name=model_name,
        api_key=settings.anthropic_api_key,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        stop=None,
        callbacks=callbacks,
    )
