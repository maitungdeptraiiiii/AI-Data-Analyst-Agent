from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 60.0
    artifacts_dir: Path = Path("artifacts")
    checkpoint_db_path: Path = Path("data/checkpoints.sqlite")
    python_sandbox_image: str = "analyst-python-sandbox:phase6"
    python_sandbox_network: str = "agen_analyze_analysis_internal"
    python_sandbox_timeout_seconds: float = 15.0
    python_sandbox_memory: str = "512m"
    python_sandbox_cpus: float = 1.0
    python_max_dataset_rows: int = 100_000
    sandbox_runs_dir: Path = Path(".sandbox_runs")
    python_sandbox_database_dsn: str = (
        "postgresql://executor_ro:executor_dev_password@postgres:5432/analyst"
    )
    postgres_ingest_dsn: str
    postgres_executor_dsn: str
    planner_model: str = "claude-sonnet-5"
    executor_model: str = "claude-sonnet-5"
    critic_model: str = "claude-sonnet-5"
    reporter_model: str = "claude-sonnet-5"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_selected_provider_key(self) -> "Settings":
        if self.llm_provider == "anthropic" and self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if self.llm_provider == "openai" and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.python_sandbox_timeout_seconds <= 0 or self.python_max_dataset_rows <= 0:
            raise ValueError("Python sandbox limits must be positive")
        self.sandbox_runs_dir.mkdir(parents=True, exist_ok=True)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
