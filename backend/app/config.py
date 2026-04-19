# app/config.py
"""
Configuration via environment variables using pydantic-settings.
"""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # GitHub App (user OAuth)
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    github_app_slug: str = ""  # e.g. "github-reporter" — used to build the install URL

    # Admin & access control
    admin_github_login: str = ""  # GitHub username of the admin user
    require_access_code: bool = True  # Require access code for new users

    # Session / encryption
    session_secret: str = "change-me-in-production"

    # Frontend URL (for OAuth redirect after callback)
    app_url: str = "http://localhost:3200"

    # LLM defaults
    default_llm_provider: str = "gemini"
    default_llm_model: str = "gemini-3-flash-preview"

    # LLM provider API keys
    google_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "github_reporter"

    # Redis — powers durable chat runs (event buffer + cancel pub/sub).
    # Required: without it, chat streaming cannot reconnect or survive worker restarts.
    redis_url: str = "redis://localhost:6379/0"
    # TTL (seconds) runs linger after a terminal event, so late reconnects can replay.
    run_ttl_seconds: int = 600
    # How often the producer heartbeats its run. Stale runs beyond 3× this are treated as orphaned.
    run_heartbeat_seconds: int = 5

    # Server
    cors_origins: str = "*"

    # Automations scheduler
    scheduler_timezone: str = "Europe/Berlin"
    scheduler_enabled: bool = True  # set False in tests / when running migrations

    # SMTP — used for automation email notifications. Works with any SMTP provider
    # (Resend, Postmark, Sendgrid SMTP, Gmail, Mailgun…).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True  # STARTTLS; set False for implicit TLS on port 465 (smtp_use_ssl)
    smtp_use_ssl: bool = False
    smtp_from: str = ""  # e.g. "GitHub Reporter <reports@yourdomain.com>"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def export_to_env(self):
        """
        Export LLM provider keys to os.environ so that SDKs
        (google-genai, openai, anthropic) can discover them.
        """
        _export = {
            "GOOGLE_API_KEY": self.google_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
        }
        for key, value in _export.items():
            if value and not os.environ.get(key):
                os.environ[key] = value


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    settings.export_to_env()
    return settings
