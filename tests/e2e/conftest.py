from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "docker-compose.yml"


def _enabled() -> bool:
    return os.getenv("AIHUB_E2E_RUN", "").lower() in {"1", "true", "yes"}


def _project() -> str:
    project = os.getenv("AIHUB_COMPOSE_PROJECT_NAME")
    if not project:
        pytest.fail("set AIHUB_COMPOSE_PROJECT_NAME to the compose project under test")
    return project


@pytest.fixture(scope="session")
def compose():
    if not _enabled():
        pytest.skip("set AIHUB_E2E_RUN=1 to run Docker Compose e2e tests")
    if subprocess.run(["docker", "compose", "version"], check=False, capture_output=True).returncode:
        pytest.fail("AIHUB_E2E_RUN is set but Docker Compose is unavailable")
    # Explicit -p: never fall back to the production project name "aihub".
    command = ["docker", "compose", "-p", _project(), "-f", os.getenv("AIHUB_COMPOSE_FILE", str(COMPOSE))]
    override = os.getenv("AIHUB_COMPOSE_OVERRIDE")
    if override:
        command.extend(["-f", override])
    env = os.environ.copy()
    manage = os.getenv("AIHUB_E2E_MANAGE_COMPOSE", "").lower() in {"1", "true", "yes"}
    if manage:
        subprocess.run([*command, "up", "-d", "--build"], env=env, check=True)
    try:
        yield command
    finally:
        if manage:
            subprocess.run([*command, "down"], env=env, check=True)


@pytest.fixture(scope="session")
def compose_env():
    return os.environ.copy()
