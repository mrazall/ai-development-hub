"""Test database endpoint from the runtime contract; dev defaults (scripts/dev/dev-db.sh) otherwise.

CI sets AIHUB_DATABASE_URL / AIHUB_DB_PASSWORD_FILE to a throwaway Postgres and AIHUB_REQUIRE_INTEGRATION=1,
so an unreachable database fails the run instead of silently skipping integration tests.
"""
import os
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

DEV_URL = "postgresql+psycopg://aihub@127.0.0.1:55432/aihub_test"  # never the dev server database
DEV_PASSWORD = "aihub-dev-only"


def test_database_url() -> str:
    url = make_url(os.environ.get("AIHUB_DATABASE_URL", DEV_URL))
    password_file = os.environ.get("AIHUB_DB_PASSWORD_FILE")
    if password_file:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    else:
        password = url.password or os.environ.get("AIHUB_DB_PASSWORD", DEV_PASSWORD)
    return url.set(password=password).render_as_string(hide_password=False)


test_database_url.__test__ = False  # not a test, despite the name


def skip_or_fail(reason: str) -> None:
    if os.environ.get("AIHUB_REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"integration dependency required in this run: {reason}")
    pytest.skip(reason)


def import_worker():
    """Import the real worker, failing instead of silently skipping when required."""
    try:
        return import_module("aihub_agents.worker").Worker
    except ImportError as exc:
        skip_or_fail(f"aihub_agents.worker is unavailable: {exc}")
        raise AssertionError("skip_or_fail() must not return")
