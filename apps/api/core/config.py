"""
Application configuration via pydantic-settings.
All values come from environment variables or a .env file.
No secrets are hardcoded here.
"""
from __future__ import annotations

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────
    APP_ENV: str = "development"           # "development" | "production"
    APP_SECRET: str = "CHANGE_ME"          # Used for JWT signing — must be overridden
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # ── API server ────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # ── Database (PostgreSQL) ─────────────────────────────────
    # Async URL for SQLAlchemy (asyncpg driver)
    DATABASE_URL: str = "postgresql+asyncpg://agen:agen_pass@localhost:5432/agen"
    # Sync URL for Alembic migrations only
    DATABASE_URL_SYNC: str = "postgresql://agen:agen_pass@localhost:5432/agen"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Auth ──────────────────────────────────────────────────
    OWNER_EMAIL: str = ""                  # Must be set in .env
    OWNER_PASSWORD_HASH: str = ""          # bcrypt hash — see QUICKSTART.md
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440         # 24 hours

    # ── AI / Nemotron ─────────────────────────────────────────
    # Phase 1: interface is defined but AI calls are not made by default.
    # Set NEMOTRON_ENABLED=true only when you have a valid API key.
    NEMOTRON_ENABLED: bool = False
    NEMOTRON_API_KEY: str = ""
    NEMOTRON_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NEMOTRON_MODEL: str = "nvidia/llama-3.1-nemotron-ultra-253b-v1"

    # ── Future integrations (not used in Phase 1) ─────────────
    # These are documented here so .env.example is complete,
    # but no code in Phase 1 reads or uses them.
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GOOGLE_MAPS_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    VERCEL_TOKEN: str = ""

    # ── Email safeguards (enforced in Phase 3+) ───────────────
    MAX_EMAILS_PER_DAY: int = 50
    MAX_EMAILS_PER_CAMPAIGN: int = 200
    EMAIL_COOLDOWN_HOURS: int = 72

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def database_available(self) -> bool:
        """True if a non-default DATABASE_URL is configured."""
        return "CHANGE_ME" not in self.DATABASE_URL

    @property
    def redis_available(self) -> bool:
        """True if a non-default REDIS_URL is configured."""
        return bool(self.REDIS_URL)


settings = Settings()
