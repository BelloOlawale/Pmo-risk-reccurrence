"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RISKAPP_", env_file=".env")

    database_url: str = "sqlite:///./riskapp.db"
    environment: str = "dev"


settings = Settings()
