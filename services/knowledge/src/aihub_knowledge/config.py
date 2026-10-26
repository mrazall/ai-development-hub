from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret_file(path: Path, *, environment: str, name: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        if environment == "test":
            return ""
        raise ValueError(f"{name} does not exist: {path}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read {name}: {path}") from exc
    if not value and environment != "test":
        raise ValueError(f"{name} is empty: {path}")
    return value


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://aihub@127.0.0.1:55432/aihub"
    db_password_file: Path | None = None
    db_password: str | None = None
    qdrant_url: str = "http://127.0.0.1:56333"
    vault_dir: Path = Path("AI-Knowledge")
    embed_backend: str = "fake"
    ollama_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_version: str = "1"
    embedding_batch_size: int = 16
    embedding_rate_per_second: float = 0.0
    internal_secret: str = ""
    internal_secret_file: Path | None = None
    environment: str = Field(default="dev", validation_alias="AIHUB_ENV")
    chunk_size: int = 1200
    chunk_overlap: int = 150
    model_config = SettingsConfigDict(env_prefix="AIHUB_", env_file=".env", extra="ignore")

    def model_post_init(self, __context: object, /) -> None:
        if self.db_password_file:
            self.db_password = _read_secret_file(
                self.db_password_file, environment=self.environment, name="AIHUB_DB_PASSWORD_FILE"
            )
        if self.internal_secret_file:
            self.internal_secret = _read_secret_file(
                self.internal_secret_file, environment=self.environment, name="AIHUB_INTERNAL_SECRET_FILE"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def database_url(settings: Settings | None = None) -> str:
    """Return the configured database URL with the password safely applied."""
    from sqlalchemy.engine import make_url

    settings = settings or get_settings()
    url = make_url(settings.database_url)
    if settings.db_password_file:
        password = _read_secret_file(
            settings.db_password_file, environment=settings.environment, name="AIHUB_DB_PASSWORD_FILE"
        )
        url = url.set(password=password)
    elif settings.db_password is not None:
        url = url.set(password=settings.db_password)
    return url.render_as_string(hide_password=False)
