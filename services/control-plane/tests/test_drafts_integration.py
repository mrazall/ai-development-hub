"""Agent drafts: the hub lists them from knowledge and applies one through a vault session on the worker."""
import pytest

from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, Session
from aihub_control.routers import knowledge as knowledge_router
from test_api_integration import admin_token, auth, clean_schema, client

pytestmark = pytest.mark.integration

DRAFT = {
    "id": "alpha/20261026-101500-Сеть.md", "project_id": "alpha", "name": "20261026-101500-Сеть.md",
    "title": "Сеть", "kind": "draft", "status": "new", "created_at": "2026-10-26T10:15:00+00:00",
    "applied_commit": None, "content": "Новый порт SSH: 2222",
}


@pytest.fixture
def vault(monkeypatch):
    monkeypatch.setenv("AIHUB_VAULT_WORKER_ID", "vault-worker")
    monkeypatch.setenv("AIHUB_VAULT_WORKDIR", "/home/dev/vault")
    state = {"draft": dict(DRAFT)}
    monkeypatch.setattr(knowledge_router, "_proxy", lambda path, *_args, **_kw: (
        [{k: v for k, v in state["draft"].items() if k != "content"}] if path == "/drafts" else dict(state["draft"])
    ))
    return state


def _worker(client, token):  # noqa: F811
    assert client.post("/api/v0/workers", headers=auth(token),
                       json={"id": "vault-worker", "host": "local", "kind": "linux"}).status_code == 200
    assert client.post("/api/v0/accounts", headers=auth(token), json={
        "id": "claude-vault", "name": "Claude", "kind": "claude_code_subscription", "worker_id": "vault-worker",
    }).status_code == 201


def test_apply_starts_a_vault_session_with_the_draft(client, admin_token, vault):  # noqa: F811
    _worker(client, admin_token)
    applied = client.post("/api/v0/knowledge/drafts/alpha/20261026-101500-Сеть.md/apply", headers=auth(admin_token))
    assert applied.status_code == 201, applied.text
    session_id = applied.json()["session_id"]
    _, factory = get_session_factory()
    db = factory()
    try:
        session = db.get(Session, session_id)
        assert (session.role, session.model, session.workdir) == ("vault", "claude-sonnet-5-5", "/home/dev/vault")
        assert session.workspace_ref == "draft:alpha/20261026-101500-Сеть.md"
        prompt = db.query(AgentEvent).filter_by(session_id=session_id).one().payload["text"]
        assert "Новый порт SSH: 2222" in prompt and "git commit" in prompt
    finally:
        db.close()
    # One session per draft at a time; the list shows it.
    assert client.post("/api/v0/knowledge/drafts/alpha/20261026-101500-Сеть.md/apply",
                       headers=auth(admin_token)).status_code == 409
    listed = client.get("/api/v0/knowledge/drafts", headers=auth(admin_token)).json()
    assert listed["apply_available"] is True
    assert listed["items"][0]["session"]["id"] == session_id


def test_revert_needs_an_applied_draft(client, admin_token, vault):  # noqa: F811
    _worker(client, admin_token)
    url = "/api/v0/knowledge/drafts/alpha/20261026-101500-Сеть.md/revert"
    assert client.post(url, headers=auth(admin_token)).status_code == 409
    vault["draft"]["status"] = "applied"
    assert client.post(url, headers=auth(admin_token)).status_code == 201
