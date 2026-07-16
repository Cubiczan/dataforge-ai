"""Configuration for DataForge AI.

Loads from environment variables with sensible defaults for local development
against `datahub docker quickstart`.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class Settings(BaseSettings):
    """Runtime configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- DataHub connection -------------------------------------------------
    datahub_gms_url: str = "http://localhost:8080"
    datahub_gms_token: Optional[str] = None
    datahub_frontend_url: str = "http://localhost:9002"

    # --- LLM provider -------------------------------------------------------
    llm_provider: LLMProvider = LLMProvider.OPENAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # --- Detector thresholds ------------------------------------------------
    freshness_sla_hours: int = 24
    schema_drift_severity: Severity = Severity.WARN
    distribution_psi_threshold: float = 0.2
    distribution_ks_pvalue: float = 0.05

    # --- Agent runtime ------------------------------------------------------
    agent_poll_interval_seconds: int = 300
    agent_dry_run: bool = False

    # --- Optional MCP server endpoint --------------------------------------
    mcp_server_url: Optional[str] = None

    # --- Storage ------------------------------------------------------------
    state_dir: Path = Path(".dataforge/state")

    @property
    def gms_auth_header(self) -> dict[str, str]:
        if self.datahub_gms_token:
            return {"Authorization": f"Bearer {self.datahub_gms_token}"}
        return {}


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Clear the cached settings (used in tests)."""
    global _settings
    _settings = None
