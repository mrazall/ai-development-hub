"""Execution run lifecycle and historical attribution against PostgreSQL."""
# ruff: noqa: F811
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from test_api_integration import admin_token, auth, clean_schema, client, make_project, make_session
from test_orchestration_integration import _create, _orch_token, _setup
from aihub_control.analytics.runs import run_of_event, runs_for_sessions
from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, ExecutionRun, Session

pytestmark = pytest.mark.integration


def _runs(db, sid):
    return list(db.scalars(select(ExecutionRun).where(ExecutionRun.session_id == sid).order_by(ExecutionRun.run_index)))


def _post(client, token, sid, events):
    response = client.post(f"/api/v0/sessions/{sid}/events", headers=auth(token), json=events)
    assert response.status_code == 200, response.text
    return response.json()


def test_duplicate_event_does_not_resume_twice(client, admin_token):
    _setup(client, admin_token)
    sid = _create(client, admin_token).json()["session_id"]
    _, factory = get_session_factory()
    with factory() as db:
        session = db.get(Session, sid)
        session.status, session.engine_session_ref = "completed", "thread-1"
        db.commit()
    event = {"kind": "message", "client_event_id": "same-event", "payload": {"role": "user", "text": "continue"}}
    first = _post(client, admin_token, sid, [event])
    # Simulate the resumed work finishing before the client retries its request.
    with factory() as db:
        db.get(Session, sid).status = "completed"
        db.commit()
    second = _post(client, admin_token, sid, [event])
    assert first[0]["cursor"] == second[0]["cursor"]
    with factory() as db:
        assert len(_runs(db, sid)) == 1
        assert len(list(db.scalars(select(AgentEvent).where(AgentEvent.session_id == sid, AgentEvent.client_event_id == "same-event")))) == 1


@pytest.mark.parametrize(("status", "trigger"), [("completed", "continue"), ("failed", "retry_after_failure")])
def test_continue_creates_second_run(client, admin_token, status, trigger):
    make_project(client, admin_token)
    sid = make_session(client, admin_token)["id"]
    _, factory = get_session_factory()
    with factory() as db:
        session = db.get(Session, sid)
        session.status, session.engine_session_ref = status, "thread-1"
        db.commit()
    response = client.post(f"/api/v0/sessions/{sid}/continue", headers=auth(admin_token), json={"text": "more"})
    assert response.status_code == 201, response.text
    assert response.json()["id"] == sid
    with factory() as db:
        runs = _runs(db, sid)
        assert [(run.run_index, run.trigger) for run in runs] == [(1, "initial"), (2, trigger)]
        events = list(db.scalars(select(AgentEvent).where(AgentEvent.session_id == sid)))
        assert any(event.run_id == runs[1].id for event in events)


def test_reused_executor_creates_rework_run(client, admin_token):
    _setup(client, admin_token)
    sid = _create(client, admin_token, count=1).json()["session_id"]
    token = _orch_token(sid)
    url = f"/api/v0/orchestrations/{sid}/executors"
    first = client.post(url, headers=auth(token), json={"title": "First", "prompt": "work"})
    assert first.status_code == 201, first.text
    _, factory = get_session_factory()
    with factory() as db:
        db.get(Session, first.json()["id"]).status = "completed"
        db.commit()
    second = client.post(url, headers=auth(token), json={"title": "Fix", "prompt": "rework", "reuse_branch_of": first.json()["id"]})
    assert second.status_code == 201, second.text
    assert second.json()["branch"] == first.json()["branch"]
    with factory() as db:
        runs = _runs(db, second.json()["id"])
        assert len(runs) == 1 and runs[0].trigger == "rework"
        assert runs[0].orchestration_id == sid


def test_wait_intervals_are_measured_only_when_closed(client, admin_token):
    make_project(client, admin_token)
    sid = make_session(client, admin_token)["id"]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def status(seconds, value, **payload):
        return {"kind": "session.status", "ts": (start + timedelta(seconds=seconds)).isoformat(),
                "payload": {"status": value, **payload}}
    _post(client, admin_token, sid, [status(0, "starting"), status(1, "running"), status(10, "waiting_approval"),
                                   status(30, "running"), status(40, "blocked", reason="limit"), status(55, "running")])
    _, factory = get_session_factory()
    with factory() as db:
        run = _runs(db, sid)[0]
        assert run.waiting_approval_s == 20 and run.waiting_limit_s == 15
    other = make_session(client, admin_token)["id"]
    _post(client, admin_token, other, [status(0, "starting"), status(1, "running"), status(10, "waiting_approval")])
    with factory() as db:
        run = _runs(db, other)[0]
        assert run.waiting_approval_s is None and run.waiting_limit_s is None


@pytest.mark.parametrize("changed", [False, True])
def test_reconstruct_legacy_runs_and_event_attribution(client, admin_token, changed):
    make_project(client, admin_token)
    response = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "demo", "worker_id": "worker-a", "engine": "codex", "provider": "openai",
        "model": "legacy", "auth_mode": "subscription", "workdir": "/tmp/project", "hold": True})
    assert response.status_code == 200, response.text
    sid = response.json()["id"]
    _, factory = get_session_factory()
    with factory() as db:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i, (kind, payload) in enumerate([
            ("session.status", {"status": "queued"}), ("session.status", {"status": "completed"}),
            ("session.status", {"status": "queued"}),
            ("session.model_changed" if changed else "message", {"text": "legacy"}),
            ("session.status", {"status": "completed"}),
        ]):
            db.add(AgentEvent(session_id=sid, kind=kind, source="native", payload=payload, ts=start + timedelta(seconds=i)))
        db.commit()
        events = list(db.scalars(select(AgentEvent).where(AgentEvent.session_id == sid).order_by(AgentEvent.cursor)))
        assert not _runs(db, sid)
        runs = runs_for_sessions(db, [sid])[sid]
        assert len(runs) == 2
        assert [run.attribution for run in runs] == ["unknown" if changed else "estimated"] * 2
        assert [run_of_event(runs, event.cursor, event.ts).run_index for event in events] == [1, 1, 2, 2, 2]
        assert runs[0].model == (None if changed else "legacy")
