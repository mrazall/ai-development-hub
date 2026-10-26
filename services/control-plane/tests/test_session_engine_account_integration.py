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
