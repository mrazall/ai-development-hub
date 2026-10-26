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


def test_continue_creates_child_and_preserves_execution_fields(client, admin_token):  # noqa: F811
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
        json={"text": "Continue the work", "fresh": True},
    )
    assert response.status_code == 201
    child = response.json()
    assert child["parent_session_id"] == original["id"]
    assert child["title"] == "Resume me"
    assert child["context_fresh"] is True

    _, factory = get_session_factory()
    db = factory()
    event = db.query(AgentEvent).filter(AgentEvent.session_id == child["id"]).one()
    assert event.payload["text"] == "Continue the work"
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
