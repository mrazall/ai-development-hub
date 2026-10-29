import pytest

from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, Session
from test_api_integration import admin_token, auth, clean_schema, client, make_project


pytestmark = pytest.mark.integration


def _session(client, token, engine="claude_code"):  # noqa: F811
    response = client.post(
        "/api/v0/sessions",
        headers=auth(token),
        json={
            "project_id": "resume-project", "worker_id": "worker-a", "engine": engine,
            "provider": "anthropic", "model": "sonnet", "auth_mode": "subscription",
            "workdir": "/tmp/project", "title": "Resume me",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_continue_runs_the_same_session_again(client, admin_token):  # noqa: F811
    # The owner: «пусть в той же сессии идёт, если я захочу, я сам новую открою».
    make_project(client, admin_token, "resume-project")
    original = _session(client, admin_token)
    _, factory = get_session_factory()
    db = factory()
    db.query(Session).filter(Session.id == original["id"]).update({
        "status": "completed", "engine_session_ref": "claude-session-1", "context_tokens": 42,
    })
    db.commit()
    db.close()

    response = client.post(
        f"/api/v0/sessions/{original['id']}/continue",
        headers=auth(admin_token),
        json={"text": "Continue the work", "fresh": True, "permission_mode": "auto"},
    )
    assert response.status_code == 201
    same = response.json()
    assert same["id"] == original["id"] and same["status"] == "queued"
    assert same["title"] == "Resume me" and same["context_fresh"] is True and same["permission_mode"] == "auto"
    assert same["engine_session_ref"] == "claude-session-1"

    _, factory = get_session_factory()
    db = factory()
    assert db.query(Session).filter(Session.parent_session_id == original["id"]).count() == 0
    texts = [e.payload["text"] for e in db.query(AgentEvent).filter(AgentEvent.session_id == original["id"],
                                                                   AgentEvent.kind == "message")]
    assert texts == ["Continue the work"]
    db.close()


def test_continue_codex_needs_its_thread_reference(client, admin_token):  # noqa: F811
    make_project(client, admin_token, "resume-project")
    codex = _session(client, admin_token, "codex")
    _, factory = get_session_factory()
    db = factory()
    db.query(Session).filter(Session.id == codex["id"]).update({"status": "completed"})
    db.commit()
    db.close()
    missing = client.post(
        f"/api/v0/sessions/{codex['id']}/continue", headers=auth(admin_token), json={"text": "x"}
    )
    assert missing.status_code == 409 and "ссылки" in missing.json()["detail"]
    db = factory()
    db.query(Session).filter(Session.id == codex["id"]).update({"engine_session_ref": "codex-thread-1"})
    db.commit()
    db.close()
    resumed = client.post(
        f"/api/v0/sessions/{codex['id']}/continue", headers=auth(admin_token), json={"text": "доделай"}
    )
    assert resumed.status_code == 201 and resumed.json()["engine"] == "codex"

    claude = _session(client, admin_token)
    _, factory = get_session_factory()
    db = factory()
    db.query(Session).filter(Session.id == claude["id"]).update({"status": "failed"})
    db.commit()
    db.close()
    response = client.post(
        f"/api/v0/sessions/{claude['id']}/continue", headers=auth(admin_token), json={"text": "x"}
    )
    assert response.status_code == 409
    assert "ссылки" in response.json()["detail"]
