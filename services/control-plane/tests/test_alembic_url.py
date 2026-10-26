"""Regression (orchestrator, integration fix 1): '%' in URL-encoded passwords breaks Alembic's ConfigParser."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError

SERVICE_DIR = Path(__file__).resolve().parents[1]


def test_alembic_env_accepts_percent_in_password(tmp_path, monkeypatch):
    (tmp_path / "pw").write_text("a/b+c=d%e", encoding="utf-8")
    (tmp_path / "sk").write_text("k" * 48, encoding="utf-8")
    monkeypatch.setenv("AIHUB_ENV", "test")
    monkeypatch.setenv("AIHUB_DB_PASSWORD_FILE", str(tmp_path / "pw"))
    monkeypatch.setenv("AIHUB_SECRET_KEY_FILE", str(tmp_path / "sk"))
    monkeypatch.setenv("AIHUB_DATABASE_URL", "postgresql+psycopg://aihub@127.0.0.1:1/aihub")
    config = Config(str(SERVICE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_DIR / "alembic"))
    # Port 1 is closed: reaching a connection error proves the URL got past ConfigParser.
    with pytest.raises(OperationalError):
        command.current(config)
