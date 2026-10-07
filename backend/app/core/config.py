import pathlib
from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.research.errors import ResearchProviderConfigurationError

ROOT_DIR = pathlib.Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+psycopg://oil:change-me@localhost:5432/engine_oil"

    # Application
    app_env: str = "development"
    log_level: str = "INFO"

    # OpenRouter
    openrouter_api_key: str | None = None
    openrouter_api_keys: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 90
    openrouter_app_name: str = "SnappCarFix"
    openrouter_app_url: str | None = None

    # Resin proxy
    resin_enabled: bool = False
    resin_proxy_url: str = "http://127.0.0.1:2260"
    resin_proxy_token: str | None = None
    resin_admin_url: str = "http://127.0.0.1:2260"
    resin_admin_token: str | None = None
    resin_platform_name: str = "OpenRouter"
    resin_platform_id: UUID | None = None
    resin_control_timeout_seconds: float = 5
    openrouter_resin_account: str = "openrouter-default"

    # OpenCode
    opencode_command: str = "opencode"
    opencode_agent: str = "oil-research"
    opencode_timeout_seconds: float = 90
    opencode_model: str | None = None
    opencode_server_url: str | None = None
    opencode_debug_logs: bool = False

    # Gemini
    gemini_api_key: str | None = None
    gemini_api_keys: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_stage1_timeout_seconds: float = 45
    gemini_stage2_timeout_seconds: float = 20
    gemini_total_timeout_seconds: float = 65
    gemini_temperature: float = 0.1
    gemini_max_output_tokens: int = 3072

    # Research and matching
    research_provider: Literal["opencode", "openrouter", "gemini"] = "gemini"
    research_min_confidence: float = 0.80
    research_web_search_enabled: bool = True
    matching_strategy: Literal["deterministic", "provider_catalog"] = "deterministic"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_provider_matching_pair(self):
        if (
            self.matching_strategy == "provider_catalog"
            and self.research_provider != "gemini"
        ):
            raise ResearchProviderConfigurationError(
                "MATCHING_STRATEGY=provider_catalog is supported only by Gemini"
            )
        return self

    @model_validator(mode="after")
    def validate_resin_configuration(self):
        if not self.resin_enabled:
            return self
        required = {
            "RESIN_PROXY_TOKEN": self.resin_proxy_token,
            "RESIN_ADMIN_TOKEN": self.resin_admin_token,
            "RESIN_PLATFORM_ID": self.resin_platform_id,
            "RESIN_PLATFORM_NAME": self.resin_platform_name,
            "OPENROUTER_RESIN_ACCOUNT": self.openrouter_resin_account,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ResearchProviderConfigurationError(
                "Resin is enabled but required configuration is missing: "
                + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
