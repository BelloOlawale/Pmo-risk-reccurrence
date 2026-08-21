"""Application configuration loaded from environment variables."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RISKAPP_", env_file=".env")

    database_url: str = "sqlite:///./riskapp.db"
    environment: str = "dev"
    app_timezone: str = "Africa/Lagos"

    @property
    def tz(self) -> ZoneInfo:
        """Business timezone for date-only anchors (e.g. the SLA start date)."""
        return ZoneInfo(self.app_timezone)


settings = Settings()
