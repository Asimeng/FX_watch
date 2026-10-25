"""Application settings, loaded from environment variables (and an optional .env file).

On Streamlit Community Cloud, root-level entries in the app's secrets are exposed as
environment variables, so the same names work there. On GitHub Actions they come from
repository secrets.
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

_DEV_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core -----------------------------------------------------------------------------
    environment: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///data/fxwatch.db"
    secret_key: str = _DEV_SECRET
    app_base_url: str = "http://localhost:8501"
    app_name: str = "FX Watch"

    # --- logging --------------------------------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    # --- email ----------------------------------------------------------------------------
    mail_backend: Literal["smtp", "console"] = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = 20.0
    mail_from: str = ""
    mail_from_name: str = "FX Watch"
    mail_reply_to: str = ""

    # --- data sources ---------------------------------------------------------------------
    http_timeout_seconds: float = 20.0
    http_user_agent: str = "FXWatch/1.0 (+https://github.com/Asimeng/webscraping)"
    # History loaded the first time a source is seen, capped at each source's earliest date.
    backfill_days: int = Field(default=3650, ge=0)
    cross_check_tolerance_pct: float = Field(default=2.0, gt=0)

    # --- alerts & abuse protection --------------------------------------------------------
    max_active_alerts_per_email: int = 20
    alert_creations_per_email_per_hour: int = 5
    alert_creations_per_ip_per_hour: int = 15
    manage_link_requests_per_email_per_hour: int = 3
    confirmation_token_max_age_hours: int = 48
    default_alert_lifetime_days: int = 90
    expiry_reminder_days: int = 7
    max_send_attempts: int = 5

    # --- worker ---------------------------------------------------------------------------
    worker_interval_minutes: int = 60

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        # Hosted Postgres providers hand out postgres:// or postgresql:// URLs; SQLAlchemy
        # needs the driver spelled out to use psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sender_address(self) -> str:
        return self.mail_from or self.smtp_username

    def validate_for_production(self) -> list[str]:
        """Return a list of configuration problems that would break a real deployment."""
        problems = []
        if self.secret_key == _DEV_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a random value of at least 32 characters.")
        if self.mail_backend == "smtp" and not (self.smtp_username and self.smtp_password):
            problems.append("SMTP_USERNAME and SMTP_PASSWORD are required for MAIL_BACKEND=smtp.")
        if self.app_base_url.startswith("http://localhost"):
            problems.append("APP_BASE_URL still points at localhost; links in emails will break.")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production":
        for problem in settings.validate_for_production():
            log.error("Configuration problem: %s", problem)
    elif settings.secret_key == _DEV_SECRET:
        log.warning("Using the development SECRET_KEY; never do this in production.")
    return settings


def generate_secret_key() -> str:
    return secrets.token_urlsafe(48)
