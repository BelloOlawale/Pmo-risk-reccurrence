"""Application configuration loaded from environment variables."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RISKAPP_", env_file=".env")

    database_url: str = "sqlite:///./riskapp.db"
    environment: str = "dev"
    app_timezone: str = "Africa/Lagos"

    # Azure OpenAI (embeddings + chat completions)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_chat_deployment: str = "gpt-4.1-mini"
    azure_openai_api_version: str = "2024-02-01"

    # Frontend base URL for email deep links.
    app_base_url: str = "http://localhost:5173"

    # Comma-separated list of allowed CORS origins (the React dev server / web app).
    cors_origins: str = "http://localhost:5173"

    # Azure Communication Services (email notifications).
    acs_endpoint: str = ""
    acs_access_key: str = ""
    acs_sender_email: str = ""

    # Redis broker for Celery (scheduler + worker).
    redis_url: str = "redis://localhost:6379/0"

    # Entra ID (M365) SSO / RBAC. Empty values mean dev mode (header-based).
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_role_group_ids: str = ""  # JSON mapping role name -> group object id

    @property
    def tz(self) -> ZoneInfo:
        """Business timezone for date-only anchors (e.g. the SLA start date)."""
        return ZoneInfo(self.app_timezone)


settings = Settings()
