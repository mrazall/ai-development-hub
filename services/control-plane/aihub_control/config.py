from pathlib import Path
import os

from sqlalchemy.engine import make_url

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str | None = None
    secret_key: str | None = None
    secret_key_file: str | None = None
    db_password_file: str | None = None
    internal_secret: str | None = None
    internal_secret_file: str | None = None
    environment: str = "development"
    access_token_ttl_s: int = 3600
    api_version: str = "0.1"
    knowledge_url: str = "http://knowledge:8000"
    # Address workers and agents use to reach the hub (MCP, orchestration API). Set it in deployment.
    public_url: str = "http://127.0.0.1:8000"
    # Origins the panel may embed (Codeman terminals), CSP frame-src syntax; empty = no frames.
    frame_src: str = ""
    # How the owner opens a shell on a worker machine, shown in CLI login instructions.
    worker_shell_hint: str = ""
    model_prices: str = ""
    # tailscaled LocalAPI socket (mounted read-only) for the health page; empty = Tailscale not checked.
    tailscale_socket: str = ""
    # How often the health checks run and notify on failures (seconds); 0 = off.
    health_interval_s: int = 60
    limits_refresh_s: int = 60
    # Demo deployment (quickstart --demo): the panel offers the built-in mock engines and shows a banner.
    demo: bool = False
    # Engine of personal chats; scenario tests set a mock engine (mock_echo_prompt) instead of Claude Code.
    chat_engine: str = "claude_code"
    # System prompt of personal chats; empty = the built-in neutral one.
    chat_system_prompt: str = ""
    web_dir: str = "/app/web"
    data_dir: str = ".data/control-plane"
    # Agent drafts are applied to the owner's Obsidian vault by a Claude session on this worker, in this
    # folder (a git checkout synced with the hub's vault). Empty = applying is unavailable.
    vault_worker_id: str = ""
    vault_workdir: str = ""
    vault_model: str = "claude-sonnet-5-5"
    # Obsidian vault name for "Open in Obsidian" links; empty hides the button.
    obsidian_vault: str = ""
    claude_context_limit: int = 250_000  # same default as the worker's AIHUB_CLAUDE_CONTEXT_LIMIT; lower = cheaper turns
    model_config = SettingsConfigDict(env_prefix="AIHUB_", env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        test_mode = self.environment == "test" or os.environ.get("AIHUB_ENV") == "test"
        if not test_mode:
            if not self.database_url:
                raise ValueError("AIHUB_DATABASE_URL is required")
            if not self.secret_key and not self.secret_key_file:
                raise ValueError("AIHUB_SECRET_KEY or AIHUB_SECRET_KEY_FILE is required")
            if not self.db_password_file:
                raise ValueError("AIHUB_DB_PASSWORD_FILE is required")
            if not self.internal_secret and not self.internal_secret_file:
                raise ValueError("AIHUB_INTERNAL_SECRET or AIHUB_INTERNAL_SECRET_FILE is required")
        if self.secret_key_file:
            self.secret_key = _read_secret_file(self.secret_key_file, "AIHUB_SECRET_KEY_FILE", test_mode)
        if self.internal_secret_file:
            self.internal_secret = _read_secret_file(
                self.internal_secret_file, "AIHUB_INTERNAL_SECRET_FILE", test_mode
            )
        if not self.secret_key:
            self.secret_key = "test-only-secret-padded-to-32-bytes"
        if not self.internal_secret:
            self.internal_secret = "test-only-internal-secret"
        if not test_mode and len(self.secret_key.encode()) < 32:
            raise ValueError("AIHUB_SECRET_KEY must be at least 32 bytes")
        if self.db_password_file and self.database_url:
            password = _read_secret_file(self.db_password_file, "AIHUB_DB_PASSWORD_FILE", test_mode)
            self.database_url = database_url(self.database_url, password)
        return self

    @property
    def sync_database_url(self) -> str:
        return (self.database_url or "postgresql+psycopg://invalid").replace(
            "postgresql+asyncpg", "postgresql+psycopg"
        )


def _read_secret_file(path: str, setting_name: str, test_mode: bool) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        if test_mode:
            return ""
        raise ValueError(f"{setting_name} could not be read") from exc
    if not value and not test_mode:
        raise ValueError(f"{setting_name} is empty")
    return value


def database_url(raw_url: str, password: str | None = None) -> str:
    """Apply a password to a URL using SQLAlchemy URL semantics."""
    url = make_url(raw_url)
    if password is not None:
        url = url.set(password=password)
    return url.render_as_string(hide_password=False)
