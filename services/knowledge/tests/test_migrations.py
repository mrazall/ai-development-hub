"""Verify the knowledge schema can be recreated from zero on the dev database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from _dbenv import test_database_url
from sqlalchemy import create_engine, text


@pytest.mark.integration
def test_alembic_downgrade_base_upgrade_head():
    service = Path(__file__).parents[1]
    env = {**os.environ, "AIHUB_DATABASE_URL": test_database_url()}
    for key in ("AIHUB_DB_PASSWORD_FILE", "AIHUB_DB_PASSWORD"):
        env.pop(key, None)  # password is already in the URL
    engine = create_engine(env["AIHUB_DATABASE_URL"])
    with engine.connect() as connection:
        public_version_before = connection.execute(
            text("SELECT to_regclass('public.alembic_version')")
        ).scalar_one()
        public_revisions_before = (
            connection.execute(text("SELECT version_num FROM public.alembic_version ORDER BY version_num"))
            .scalars()
            .all()
            if public_version_before
            else []
        )
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=service, env=env, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=service, env=env, check=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('knowledge.alembic_version')")).scalar_one() == (
            "knowledge.alembic_version"
        )
        assert connection.execute(text("SELECT version_num FROM knowledge.alembic_version")).scalar_one() == (
                "0004_document_types"
        )
        assert connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar_one() == public_version_before
        public_revisions_after = (
            connection.execute(text("SELECT version_num FROM public.alembic_version ORDER BY version_num"))
            .scalars()
            .all()
            if public_version_before
            else []
        )
        assert public_revisions_after == public_revisions_before
    engine.dispose()
