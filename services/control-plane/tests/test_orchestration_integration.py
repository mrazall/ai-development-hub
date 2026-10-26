"""Orchestrator mode: creation checks, executor limit, and the orchestrator token's narrow scope."""
import pytest

from test_api_integration import admin_token, auth, client, clean_schema, make_project
from aihub_control.auth import issue_scoped_token
from aihub_control.config import Settings
from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, Session, User

pytestmark = pytest.mark.integration


def _setup(http, token):
    make_project(http, token, "orch-demo")
    worker = http.post("/api/v0/workers", headers=auth(token),
                       json={"id": "orch-worker", "host": "local", "kind": "linux"})
    assert worker.status_code == 200
    for profile_id, kind in (("claude-o", "claude_code_subscription"), ("codex-x", "codex_subscription")):
        response = http.post("/api/v0/accounts", headers=auth(token),
                               json={"id": profile_id, "name": profile_id, "kind": kind, "worker_id": "orch-worker"})
        assert response.status_code == 201
    return worker.json()["worker_token"]


def _create(http, token, count=2, orchestrator="claude-o", executor="codex-x"):
    return http.post("/api/v0/orchestrations", headers=auth(token), json={
        "project_id": "orch-demo", "title": "Demo", "spec": "Сделай две вещи.",
        "orchestrator": {"account_profile_id": orchestrator},
        "executors": {"count": count, "account_profile_id": executor, "model": "gpt-5.6-luna"},
    })


def _orch_token(session_id: str) -> str:
    _, factory = get_session_factory()
    db = factory()
    try:
        admin = db.query(User).filter_by(username="admin").one()
        return issue_scoped_token(admin, {"knowledge:read", f"orchestrate:{session_id}"}, settings=Settings()).access_token
    finally:
        db.close()


def test_orchestration_is_created_with_claude_profile_and_limits_executors(client, admin_token):  # noqa: F811
    _setup(client, admin_token)
    created = _create(client, admin_token, count=1)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    _, factory = get_session_factory()
    db = factory()
    try:
        session = db.get(Session, session_id)
        assert session.role == "orchestrator" and session.engine == "claude_code"
        assert session.account_profile_id == "claude-o"  # without it Claude would run unlogged
        assert session.orchestration["max_executors"] == 1
    finally:
        db.close()

    token = _orch_token(session_id)
    first = client.post(f"/api/v0/orchestrations/{session_id}/executors", headers=auth(token),
                        json={"title": "Part A", "prompt": "do A"})
    assert first.status_code == 201, first.text
    assert first.json()["branch"].startswith("aihub/")
    db = factory()
    try:
        # The worker only creates a git worktree when the executor carries its orchestration base.
        executor = db.get(Session, first.json()["id"])
        assert executor.orchestration["base_branch"] == "main"
        assert executor.branch == first.json()["branch"]
        assert executor.orchestration["base_workdir"] == session.orchestration["base_workdir"]
    finally:
        db.close()
    second = client.post(f"/api/v0/orchestrations/{session_id}/executors", headers=auth(token),
                         json={"title": "Part B", "prompt": "do B"})
    assert second.status_code == 409  # max_executors = 1 and the first one is still active
    listed = client.get(f"/api/v0/orchestrations/{session_id}/executors", headers=auth(token))
    assert [item["title"] for item in listed.json()] == ["Part A"]


def test_orchestrator_token_is_confined_to_its_own_orchestration(client, admin_token):  # noqa: F811
    _setup(client, admin_token)
    own = _create(client, admin_token).json()["session_id"]
    other = _create(client, admin_token).json()["session_id"]
    token = _orch_token(own)
    assert client.get(f"/api/v0/orchestrations/{other}/executors", headers=auth(token)).status_code == 403
    for path in ("/api/v0/projects", "/api/v0/sessions", "/api/v0/accounts", "/api/v0/chats"):
        assert client.get(path, headers=auth(token)).status_code in (401, 403), path
    # A normal user token carries no orchestrate scope either.
    assert client.get(f"/api/v0/orchestrations/{own}/executors", headers=auth(admin_token)).status_code == 403


def test_orchestration_rejects_wrong_account_kinds(client, admin_token):  # noqa: F811
    _setup(client, admin_token)
    assert _create(client, admin_token, orchestrator="codex-x").status_code == 409
    assert _create(client, admin_token, executor="claude-o").status_code == 409


def test_delete_session_removes_finished_orchestration_with_executors(client, admin_token):  # noqa: F811
    _setup(client, admin_token)
    session_id = _create(client, admin_token).json()["session_id"]
    token = _orch_token(session_id)
    executor = client.post(f"/api/v0/orchestrations/{session_id}/executors", headers=auth(token),
                           json={"title": "Part A", "prompt": "do A"}).json()
    assert client.delete(f"/api/v0/sessions/{session_id}", headers=auth(admin_token)).status_code == 409
    _, factory = get_session_factory()
    db = factory()
    try:
        for item in db.query(Session).filter(Session.id.in_([session_id, executor["id"]])):
            item.status = "failed"
        db.commit()
    finally:
        db.close()
    assert client.delete(f"/api/v0/sessions/{session_id}", headers=auth(admin_token)).status_code == 204
    for sid in (session_id, executor["id"]):
        assert client.get(f"/api/v0/sessions/{sid}", headers=auth(admin_token)).status_code == 404


def test_continue_resumes_an_orchestrator_in_place(client, admin_token):  # noqa: F811
    _setup(client, admin_token)
    session_id = _create(client, admin_token).json()["session_id"]
    _, factory = get_session_factory()
    db = factory()
    try:
        session = db.get(Session, session_id)
        session.status, session.engine_session_ref = "completed", "claude-conversation"
        db.commit()
    finally:
        db.close()
    resumed = client.post(f"/api/v0/sessions/{session_id}/continue", headers=auth(admin_token),
                          json={"text": "Продолжай: слей ветки и открой PR"})
    assert resumed.status_code == 201, resumed.text
    # Same session: executors and the orchestrate:<id> scope stay attached to it.
    assert resumed.json()["id"] == session_id and resumed.json()["status"] == "queued"


def test_plain_message_to_a_finished_orchestrator_wakes_it_up(client, admin_token):  # noqa: F811
    # A browser tab with a stale "running" status posts to /events instead of /continue.
    _setup(client, admin_token)
    session_id = _create(client, admin_token).json()["session_id"]
    _, factory = get_session_factory()
    db = factory()
    try:
        session = db.get(Session, session_id)
        session.status, session.engine_session_ref = "failed", "claude-conversation"
        db.commit()
    finally:
        db.close()
    posted = client.post(f"/api/v0/sessions/{session_id}/events", headers=auth(admin_token),
                         json=[{"kind": "message", "payload": {"role": "user", "text": "продолжай"}}])
    assert posted.status_code == 200, posted.text
    assert client.get(f"/api/v0/sessions/{session_id}", headers=auth(admin_token)).json()["status"] == "queued"


def test_limit_failure_schedules_and_runs_an_auto_resume(client, admin_token):  # noqa: F811
    from datetime import datetime, timedelta, timezone

    from aihub_control.orchestration.auto_resume import RESUME_TEXT, resume_due

    worker_token = _setup(client, admin_token)
    session_id = _create(client, admin_token).json()["session_id"]
    _, factory = get_session_factory()
    db = factory()
    try:
        session = db.get(Session, session_id)
        session.status, session.engine_session_ref = "running", "claude-conversation"
        db.commit()
    finally:
        db.close()
    posted = client.post(f"/api/v0/sessions/{session_id}/events", headers=auth(worker_token), json=[
        {"kind": "message", "payload": {"role": "assistant", "text": "You've hit your session limit · resets 12am (Europe/Moscow)"}},
        {"kind": "session.status", "payload": {"status": "failed", "exit_code": 1}},
    ])
    assert posted.status_code == 200, posted.text
    body = client.get(f"/api/v0/sessions/{session_id}", headers=auth(admin_token)).json()
    assert body["status"] == "failed" and body["resume_at"]
    db = factory()
    try:
        assert resume_due(db, datetime.now(timezone.utc) + timedelta(days=1)) == 1
    finally:
        db.close()
    body = client.get(f"/api/v0/sessions/{session_id}", headers=auth(admin_token)).json()
    assert body["status"] == "queued" and body["resume_at"] is None
    db = factory()
    try:
        last = db.query(AgentEvent).filter_by(session_id=session_id).order_by(AgentEvent.cursor.desc()).first()
        assert last.payload["text"] == RESUME_TEXT
    finally:
        db.close()
