from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from aihub_knowledge.config import Settings, database_url


def test_database_url_reads_password_file_without_losing_special_characters(tmp_path: Path):
    password_file = tmp_path / "postgres_password"
    password_file.write_text("p@ss:/%word\n", encoding="utf-8")
    settings = Settings(
        database_url="postgresql+psycopg://aihub@db:5432/aihub",
        db_password_file=password_file,
    )

    assert make_url(database_url(settings)).password == "p@ss:/%word"


@pytest.mark.parametrize("contents", ["", "\n"])
def test_empty_password_file_is_rejected_outside_test(tmp_path: Path, contents: str):
    password_file = tmp_path / "postgres_password"
    password_file.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="AIHUB_DB_PASSWORD_FILE is empty"):
        Settings(db_password_file=password_file)


def test_missing_internal_secret_file_is_rejected_outside_test(tmp_path: Path):
    with pytest.raises(ValueError, match="AIHUB_INTERNAL_SECRET_FILE does not exist"):
        Settings(internal_secret_file=tmp_path / "missing")


def test_empty_internal_secret_file_is_rejected_outside_test(tmp_path: Path):
    secret_file = tmp_path / "internal_secret"
    secret_file.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AIHUB_INTERNAL_SECRET_FILE is empty"):
        Settings(internal_secret_file=secret_file)
