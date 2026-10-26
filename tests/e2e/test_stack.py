from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import pytest


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.URLError as exc:
        pytest.fail(f"health endpoint is unreachable: {url}: {exc}")


def _internal_get(compose, compose_env, service: str, path: str, token: str | None = None) -> tuple[int, str]:
    """GET from inside the service container; HTTP errors are returned as (status, body), not raised."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    code = "\n".join(
        [
            "import urllib.error, urllib.request",
            f"req = urllib.request.Request('http://{service}:8000{path}', headers={headers!r})",
            "try:",
            "    r = urllib.request.urlopen(req, timeout=5); print(r.status); print(r.read().decode())",
            "except urllib.error.HTTPError as e:",
            "    print(e.code); print(e.read().decode())",
        ]
    )
    result = subprocess.run(
        [*compose, "exec", "-T", service, "python", "-c", code],
        env=compose_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.splitlines()
    return int(lines[0]), "\n".join(lines[1:])


def _wait_healthy(compose, compose_env, service: str, timeout_s: int = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            [*compose, "ps", "--format", "{{.Health}}", service], env=compose_env, capture_output=True, text=True
        )
        if result.stdout.strip() == "healthy":
            return
        time.sleep(2)
    pytest.fail(f"{service} did not become healthy within {timeout_s}s")


@pytest.mark.parametrize("port", ["CONTROL_PLANE_PORT", "KNOWLEDGE_PORT"])
def test_health(port: str, compose, compose_env):
    configured_port = os.getenv(port, "58080" if port == "CONTROL_PLANE_PORT" else "58081")
    if os.getenv("AIHUB_E2E_INTERNAL", "").lower() in {"1", "true", "yes"}:
        service = "control-plane" if port == "CONTROL_PLANE_PORT" else "knowledge"
        path = "/api/v0/health" if service == "control-plane" else "/health"
        status, body = _internal_get(compose, compose_env, service, path)
    else:
        path = "/api/v0/health" if port == "CONTROL_PLANE_PORT" else "/health"
        status, body = _get(f"http://127.0.0.1:{configured_port}{path}")
    assert status == 200
    assert body


def test_migrations_completed_successfully(compose, compose_env):
    result = subprocess.run(
        [*compose, "ps", "--all", "--format", "json"],
        env=compose_env,
        capture_output=True,
        text=True,
        check=True,
    )
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    for service in ("migrate-control", "migrate-knowledge"):
        matching = [record for record in records if record.get("Service") == service]
        assert matching, f"missing migration service {service}"
        assert matching[0].get("ExitCode") == 0, matching[0]


def test_restart_preserves_control_plane_data(compose, compose_env):
    if os.getenv("AIHUB_E2E_ADMIN_PASSWORD") is None:
        pytest.skip("set AIHUB_E2E_ADMIN_PASSWORD to exercise authenticated persistence")
    password = os.environ["AIHUB_E2E_ADMIN_PASSWORD"]
    created = subprocess.run(
        [*compose, "exec", "-T", "-e", "AIHUB_ADMIN_PASSWORD", "control-plane", "aihub-control", "create-admin"],
        env={**compose_env, "AIHUB_ADMIN_PASSWORD": password},
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr[-2000:]
    status, token_body = _internal_post(
        compose, compose_env, "control-plane", "/api/v0/auth/login", {"username": "admin", "password": password}
    )
    assert status == 200
    token = json.loads(token_body)["access_token"]
    project = f"e2e-{os.getenv('GITHUB_RUN_ID', 'local')}"
    status, _ = _internal_post(
        compose, compose_env, "control-plane", "/api/v0/projects", {"id": project, "name": project, "visibility": "private"}, token
    )
    assert status == 201
    subprocess.run([*compose, "restart", "control-plane"], env=compose_env, check=True)
    _wait_healthy(compose, compose_env, "control-plane")
    status, body = _internal_get(compose, compose_env, "control-plane", f"/api/v0/projects/{project}", token)
    assert status == 200
    assert json.loads(body)["id"] == project


def _internal_post(compose, compose_env, service, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    code = (
        "import json, urllib.request; "
        f"r=urllib.request.Request('http://{service}:8000{path}', data=json.dumps({json.dumps(payload)}).encode(), "
        f"headers={json.dumps(headers)}, method='POST'); "
        "x=urllib.request.urlopen(r, timeout=5); print(x.status); print(x.read().decode())"
    )
    result = subprocess.run([*compose, "exec", "-T", service, "python", "-c", code], env=compose_env, capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()
    return int(lines[0]), "\n".join(lines[1:])


def test_logs_do_not_contain_secret_patterns(compose, compose_env):
    result = subprocess.run(
        [*compose, "logs", "--no-color"], env=compose_env, capture_output=True, text=True, check=True
    )
    logs = result.stdout + result.stderr
    patterns = ["postgres_password", "restic_password", "api_key", "authorization: bearer"]
    lowered = logs.lower()
    assert not any(pattern in lowered for pattern in patterns), json.dumps(patterns)
