"""Runtime configuration. Every value can be set from the environment or `.env` (see `.env.example`)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_content_root() -> Path:
    env = os.environ.get("CONTENT_ROOT")
    if env:
        return Path(env)
    # apps/api/app/core/config.py -> repository root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "prompts").is_dir() and (parent / "config").is_dir():
            return parent
    return here.parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore", case_sensitive=False)

    # Core
    app_env: str = "development"
    app_secret_key: str = "dev-insecure-secret-change-me-0000000000"
    app_base_url: str = "http://localhost:3000"
    tenant_default: str = "ten"
    log_level: str = "info"
    content_root: Path = Field(default_factory=_default_content_root)

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/dev.db"
    db_echo: bool = False

    # Model
    model_provider: str = "ollama"  # ollama | openai_compat | mock
    ollama_base_url: str = "http://localhost:11434"
    model_writer: str = "qwen2.5:7b-instruct"
    model_fast: str = "qwen2.5:3b-instruct"
    model_embed: str = "nomic-embed-text"
    model_timeout_s: int = 600
    model_concurrency: int = 1
    model_num_ctx: int = 8192
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""

    # Discovery / fetching
    fetch_user_agent: str = "LayerFlowBot/1.0 (+https://theexecutivenarrative.com; contact@theexecutivenarrative.com)"
    fetch_max_per_domain: int = 1
    fetch_global_concurrency: int = 4
    fetch_timeout_s: float = 15.0
    fetch_max_bytes: int = 3 * 1024 * 1024
    fetch_cache_dir: Path = Path("./data/cache")
    fetch_cache_days: int = 7
    fetch_min_interval_s: float = 1.0

    # Publishing
    publish_target: str = "export"  # export | ten_static | wordpress | webhook
    artifacts_dir: Path = Path("./data/artifacts")
    site_root: Path = Path("./data/site")  # local staging root for ten_static when no SFTP host is set
    ten_sftp_host: str = ""
    ten_sftp_port: int = 22
    ten_sftp_user: str = ""
    ten_sftp_key_path: str = ""
    ten_public_root: str = "/public_html"
    ten_site_url: str = "https://theexecutivenarrative.com"
    wordpress_url: str = ""
    wordpress_user: str = ""
    wordpress_app_password: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""

    # LinkedIn (optional)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = ""
    linkedin_org_urn: str = ""
    linkedin_api_version: str = "202606"
    token_encryption_key: str = ""

    # Auth
    admin_email: str = ""
    admin_password: str = ""
    session_days: int = 7
    cookie_secure: bool | None = None
    login_attempts_per_15min: int = 5
    rate_limit_mutations_per_min: int = 60
    rate_limit_reads_per_min: int = 600

    # Worker
    worker_poll_interval_s: float = 2.0
    worker_visibility_timeout_s: int = 600
    worker_heartbeat_s: int = 20
    scheduler_tick_s: int = 60
    io_concurrency: int = 2

    # Ops
    backup_dir: Path = Path("./data/backups")
    alert_webhook_url: str = ""
    disk_alert_pct: float = 85.0

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.is_production and (
            len(self.app_secret_key) < 32 or self.app_secret_key.startswith("dev-insecure")
        ):
            raise ValueError("APP_SECRET_KEY must be set to 32+ random characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production and self.app_base_url.startswith("https://")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def prompts_dir(self) -> Path:
        return self.content_root / "prompts"

    @property
    def config_dir(self) -> Path:
        return self.content_root / "config"

    @property
    def templates_dir(self) -> Path:
        return self.content_root / "templates"

    @property
    def evals_dir(self) -> Path:
        return self.content_root / "evals"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
