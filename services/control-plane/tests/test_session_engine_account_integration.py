"""A subscription account runs only its own CLI: a mismatched engine is refused before the session starts."""
import pytest

from test_api_integration import admin_token, auth, clean_schema, client, make_project

pytestmark = pytest.mark.integration


def _session(client, token, engine, account):  # noqa: F811
    return client.post("/api/v0/sessions", headers=auth(token), json={
        "project_id": "demo", "worker_id": "w1", "engine": engine, "provider": "anthropic", "model": "claude-opus-5-5",
        "auth_mode": "subscription", "workdir": "/tmp/project", "account_profile_id": account,
    })


def test_codex_with_a_claude_account_is_refused(client, admin_token):  # noqa: F811
    # Found in production: the dialog showed claude_code but sent codex → Codex had no OpenAI login (401).
    make_project(client, admin_token, "demo")
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "w1", "host": "local", "kind": "linux"})
    client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-a", "name": "Claude", "kind": "claude_code_subscription", "worker_id": "w1",
    })
    refused = _session(client, admin_token, "codex", "claude-a")
    assert refused.status_code == 422 and "claude_code" in refused.text
    assert _session(client, admin_token, "claude_code", "claude-a").status_code == 200
    # The demo's built-in mock engines need no login and run with any profile.
    assert _session(client, admin_token, "mock_write", "claude-a").status_code == 200


def test_an_account_runs_only_on_its_own_worker(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    for worker_id in ("pc", "box"):
        client.post("/api/v0/workers", headers=auth(admin_token), json={"id": worker_id, "host": "h", "kind": "linux"})
    client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-pc", "name": "Claude", "kind": "claude_code_subscription", "worker_id": "pc",
    })
    body = {"project_id": "demo", "engine": "claude_code", "provider": "anthropic", "model": "claude-opus-5-5",
            "auth_mode": "subscription", "workdir": "/tmp/project", "account_profile_id": "claude-pc"}
    refused = client.post("/api/v0/sessions", headers=auth(admin_token), json={**body, "worker_id": "box"})
    assert refused.status_code == 422 and "pc" in refused.json()["detail"]
    assert client.post("/api/v0/sessions", headers=auth(admin_token), json={**body, "worker_id": "pc"}).status_code == 200


def test_session_effort_and_worker_models(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "box", "host": "h", "kind": "linux"}).json()
    models = {"codex": [{"slug": "gpt-6.1-sol", "name": "GPT-6.1-Sol", "efforts": ["low", "max"]}]}
    client.post("/api/v0/workers/box/capabilities", headers=auth(worker["worker_token"]),
                json={"engines": {"codex": "0.165"}, "models": models})
    assert client.get("/api/v0/workers/box", headers=auth(admin_token)).json()["models"] == models
    created = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "demo", "worker_id": "box", "engine": "codex", "provider": "openai", "model": "gpt-6.1-sol",
        "auth_mode": "subscription", "workdir": "/tmp/project", "effort": "max"})
    assert created.status_code == 200
    from aihub_control.db import get_session_factory
    from aihub_control.models import Session

    _, factory = get_session_factory()
    db = factory()
    assert db.get(Session, created.json()["id"]).mcp_config["effort"] == "max"
    db.close()
    bad = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "demo", "worker_id": "box", "engine": "codex", "provider": "openai", "model": "m",
        "auth_mode": "subscription", "workdir": "/tmp/project", "effort": "turbo"})
    assert bad.status_code == 422
