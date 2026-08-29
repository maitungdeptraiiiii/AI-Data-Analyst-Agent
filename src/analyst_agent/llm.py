from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from analyst_agent.config import get_settings

ModelRole = Literal["planner", "executor", "critic", "reporter"]


class _GroqJsonSchemaChat(ChatGroq):
    """ChatGroq wrapper that forces ``method='json_schema'`` for structured output.

    Groq's ``openai/gpt-oss-*`` models intermittently fail with a 400 error
    ("Tool choice is required, but model did not call a tool") when using the
    default ``function_calling`` method.  ``json_schema`` is reliable.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def with_structured_output(
        self,
        schema: dict[str, Any] | type[BaseModel] | None = None,
        *,
        method: Literal["function_calling", "json_mode", "json_schema"] = "json_schema",
        include_raw: bool = False,
        strict: bool | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        return super().with_structured_output(
            schema,
            method=method,
            include_raw=include_raw,
            strict=strict,
            **kwargs,
        )


def create_chat_model(role: ModelRole, callbacks: list[Any] | None = None) -> BaseChatModel:
    """Create the configured provider without leaking provider logic into graph nodes."""
    settings = get_settings()
    model_name = getattr(settings, f"{role}_model")

    if settings.llm_provider == "groq":
        assert settings.groq_api_key is not None
        return _GroqJsonSchemaChat(
            model=model_name,
            groq_api_key=settings.groq_api_key.get_secret_value(),
            temperature=0,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
            callbacks=callbacks,
        )

    if settings.llm_provider in ("gemini", "google"):
        key = settings.gemini_api_key or settings.google_api_key
        assert key is not None
        return ChatGoogleGenerativeAI(
            model=model_name,
            api_key=key,
            temperature=0,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
            callbacks=callbacks,
        )

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
