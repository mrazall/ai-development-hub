"""Regression (orchestrator, integration fix 1): URL-encoded passwords contain '%', which breaks Alembic's ConfigParser."""
from __future__ import annotations

from alembic.config import Config

from aihub_knowledge.config import Settings, database_url


def test_alembic_accepts_password_with_url_encoded_chars(tmp_path):
    password_file = tmp_path / "pw"
    password_file.write_text("a/b+c=d%e\n", encoding="utf-8")
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://aihub@127.0.0.1:1/aihub",
        db_password_file=password_file,
    )
    url = database_url(settings)
    config = Config()
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    assert config.get_main_option("sqlalchemy.url") == url
