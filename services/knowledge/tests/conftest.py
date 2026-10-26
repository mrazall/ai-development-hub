"""Test-only defaults for the local development PostgreSQL instance."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from _dbenv import test_database_url
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

os.environ.setdefault("AIHUB_DB_PASSWORD", "aihub-dev-only")

SERVICE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Bring the schema to head once per session when a database is reachable.

    Integration tests must not depend on a database left migrated by earlier runs (CI starts from an empty one).
    """
    url = test_database_url()
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        yield  # unit tests still run; integration tests skip or fail on their own
        return
    finally:
        engine.dispose()
    env = {**os.environ, "AIHUB_DATABASE_URL": url}
    for key in ("AIHUB_DB_PASSWORD_FILE", "AIHUB_DB_PASSWORD"):
        env.pop(key, None)  # password is already in the URL
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=SERVICE_DIR, env=env, check=True)
    yield


@pytest.fixture(scope="session", autouse=True)
def dispose_api_engine():
    yield
    from aihub_knowledge import api

    api.engine.dispose()
