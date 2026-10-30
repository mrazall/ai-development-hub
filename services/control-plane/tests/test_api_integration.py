import contextlib
import http.client
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest
import uvicorn
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).parents[1]
from _dbenv import skip_or_fail, test_database_url

DATABASE_URL = test_database_url()
SYNC_URL = DATABASE_URL.replace("+psycopg", "")
os.environ["AIHUB_DATABASE_URL"] = DATABASE_URL
os.environ["AIHUB_SECRET_KEY"] = "integration-test-secret-0123456789abcdef"
os.environ["AIHUB_ENV"] = "test"

from aihub_control.auth import hash_password
from aihub_control.db import get_session_factory
from aihub_control.main import app
from aihub_control.models import Project, Session, User, Worker


def _postgres_available():
    try:
        with psycopg.connect(SYNC_URL, connect_timeout=2):
            return True
    except psycopg.Error:
        return False


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_schema():
    if not _postgres_available():
        skip_or_fail("PostgreSQL from AIHUB_DATABASE_URL is unavailable")
    with psycopg.connect(SYNC_URL) as connection:
        connection.execute("SET lock_timeout = '30s'")  # a leaked connection fails, never hangs
        connection.execute("DROP SCHEMA IF EXISTS control CASCADE")
        connection.commit()
    env = os.environ.copy()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=SERVICE_DIR, env=env, check=True)
    yield
    with psycopg.connect(SYNC_URL) as connection:
        connection.execute("SET lock_timeout = '30s'")  # a leaked connection fails, never hangs
        connection.execute("DROP SCHEMA IF EXISTS control CASCADE")
        connection.commit()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_token():
    _, factory = get_session_factory()
    db = factory()
    user = User(username="admin", password_hash=hash_password("admin-password"), role="admin")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    response = TestClient(app).post(
        "/api/v0/auth/login", json={"username": "admin", "password": "admin-password"}
    )
    return response.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def make_project(client, token, project_id="demo", visibility="private"):
    response = client.post(
        "/api/v0/projects",
        headers=auth(token),
        json={"id": project_id, "name": project_id, "visibility": visibility},
    )
    assert response.status_code == 201
    return response.json()


def make_session(client, token, project_id="demo", worker_id="worker-a"):
    response = client.post(
        "/api/v0/sessions",
        headers=auth(token),
        json={
            "project_id": project_id,
            "worker_id": worker_id,
            "engine": "codex",
            "provider": "openai",
            "model": "test",
            "auth_mode": "subscription",
            "workdir": "/tmp/project",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_create_admin_has_default_id_and_login(client, admin_token):
    assert admin_token
    _, factory = get_session_factory()
    db = factory()
    user = db.query(User).filter(User.username == "admin").one()
    assert user.id
    db.close()


def test_idempotent_tasks_and_events(client, admin_token):
    make_project(client, admin_token)
    task_payload = {"title": "same", "idempotency_key": "request-1"}
    first = client.post("/api/v0/projects/demo/tasks", headers=auth(admin_token), json=task_payload)
    second = client.post(
        "/api/v0/projects/demo/tasks", headers=auth(admin_token), json=task_payload
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    session = make_session(client, admin_token)
    event = [{"kind": "stdout", "source": "native", "client_event_id": "event-1", "payload": {}}]
    first = client.post(
        f"/api/v0/sessions/{session['id']}/events", headers=auth(admin_token), json=event
    )
    second = client.post(
        f"/api/v0/sessions/{session['id']}/events", headers=auth(admin_token), json=event
    )
    assert first.status_code == second.status_code == 200
    assert first.json()[0]["cursor"] == second.json()[0]["cursor"]


def test_viewer_is_read_only_and_cannot_cross_private_project(client, admin_token):
    make_project(client, admin_token, "private-a")
    _, factory = get_session_factory()
    db = factory()
    db.add(User(username="viewer", password_hash=hash_password("viewer-password"), role="viewer"))
    db.commit()
    db.close()
    login = client.post(
        "/api/v0/auth/login", json={"username": "viewer", "password": "viewer-password"}
    )
    viewer_token = login.json()["access_token"]
    assert client.get("/api/v0/projects/private-a", headers=auth(viewer_token)).status_code == 404
    assert (
        client.post(
            "/api/v0/projects/private-a/tasks", headers=auth(viewer_token), json={"title": "nope"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v0/projects", headers=auth(viewer_token), json={"id": "nope", "name": "nope"}
        ).status_code
        == 403
    )


def test_worker_token_scope_and_offline_session(client, admin_token):
    make_project(client, admin_token)
    worker = client.post(
        "/api/v0/workers",
        headers=auth(admin_token),
        json={"id": "worker-a", "host": "local", "kind": "linux"},
    ).json()
    other_worker = client.post(
        "/api/v0/workers",
        headers=auth(admin_token),
        json={"id": "worker-b", "host": "local", "kind": "linux"},
    ).json()
    session = make_session(client, admin_token, worker_id="worker-a")
    waiting = make_session(client, admin_token, worker_id="worker-a")
    foreign_session = make_session(client, admin_token, worker_id="worker-b")
    event = [{"kind": "stdout", "payload": {"x": 1}}]
    worker_headers = auth(worker["worker_token"])
    assert (
        client.post(
            f"/api/v0/sessions/{foreign_session['id']}/events", headers=worker_headers, json=event
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v0/sessions/{session['id']}/events", headers=worker_headers, json=event
        ).status_code
        == 200
    )
    _, factory = get_session_factory()
    db = factory()
    db.get(Session, session["id"]).last_heartbeat_at = None
    db.get(Session, session["id"]).status = "running"
    db.get(Project, "demo")
    db.query(Worker).filter_by(id="worker-a").one().lease_ttl_s = 0
    db.commit()
    db.close()
    response = client.get("/api/v0/workers", headers=auth(admin_token))
    assert response.status_code == 200
    assert (
        client.get(f"/api/v0/sessions/{session['id']}", headers=auth(admin_token)).json()["status"]
        == "offline"
    )
    assert client.get(f"/api/v0/sessions/{waiting['id']}", headers=auth(admin_token)).json()["status"] == "queued"
    # The worker comes back and names the session it still runs: it is running again.
    beat = client.post("/api/v0/workers/worker-a/heartbeat", headers=worker_headers,
                       json={"active_sessions": [session["id"], foreign_session["id"]]})
    assert beat.status_code == 200
    assert client.get(f"/api/v0/sessions/{session['id']}", headers=auth(admin_token)).json()["status"] == "running"
    assert client.get(f"/api/v0/sessions/{foreign_session['id']}", headers=auth(admin_token)).json()["status"] != "running"
    # The desktop app animates its tray while the worker has running sessions (lease back, or the
    # listing marks worker-a offline again).
    db = factory()
    db.query(Worker).filter_by(id="worker-a").one().lease_ttl_s = 60
    db.commit()
    db.close()
    client.post("/api/v0/workers/worker-a/heartbeat", headers=worker_headers, json={"active_sessions": [session["id"]]})
    counts = {w["id"]: w["active_agents"] for w in client.get("/api/v0/workers", headers=auth(admin_token)).json()}
    assert counts == {"worker-a": 1, "worker-b": 0}
    # The session page's worker strip: status and last heartbeat, even before the worker sent capabilities.
    details = client.get("/api/v0/workers/worker-a", headers=auth(admin_token)).json()
    assert details["id"] == "worker-a" and details["status"] == "online" and details["last_heartbeat_at"]
    assert other_worker["worker_token"]


def test_append_only_trigger_and_event_sql_filter(client, admin_token):
    make_project(client, admin_token)
    session = make_session(client, admin_token)
    response = client.post(
        f"/api/v0/sessions/{session['id']}/events",
        headers=auth(admin_token),
        json=[{"kind": "x", "payload": {}}],
    )
    cursor = response.json()[0]["cursor"]
    with psycopg.connect(SYNC_URL) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE control.agent_events SET kind = 'changed' WHERE cursor = %s", (cursor,)
            )
            connection.commit()
        connection.rollback()
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM control.agent_events WHERE cursor = %s", (cursor,))
            connection.commit()


@contextlib.contextmanager
def live_server():
    """Real uvicorn on a free port: exercises actual HTTP streaming, unlike TestClient, and always shuts down."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not (server.started and server.servers):
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def read_first_event_id(port, token, last_event_id=None, timeout_s=20.0):
    """Open the SSE stream, return the first `id: ...` line; every socket operation is bounded."""
    headers = {**auth(token), "Accept": "text/event-stream"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout_s)
    try:
        connection.request("GET", "/api/v0/events/stream?after=0", headers=headers)
        response = connection.getresponse()
        assert response.status == 200
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = response.fp.readline().decode().strip()
            if line.startswith("id: "):
                return line
        raise AssertionError("no SSE event within timeout")
    finally:
        connection.close()


def test_sse_replay_and_last_event_id(client, admin_token):
    make_project(client, admin_token)
    session = make_session(client, admin_token)
    with live_server() as port:
        result = queue.Queue()

        def consume():
            try:
                result.put(read_first_event_id(port, admin_token))
            except Exception as exc:  # surfaced in the main thread
                result.put(exc)

        consumer = threading.Thread(target=consume, daemon=True)
        consumer.start()
        time.sleep(1.5)  # stream is open and polling before the event is written
        event = client.post(
            f"/api/v0/sessions/{session['id']}/events",
            headers=auth(admin_token),
            json=[{"kind": "sse", "payload": {}}],
        ).json()[0]
        first = result.get(timeout=30)
        assert not isinstance(first, Exception), first
        assert first == f"id: {event['cursor']}"
        # Reconnect with Last-Event-ID just before the event: it is replayed exactly once.
        assert read_first_event_id(port, admin_token, last_event_id=event["cursor"] - 1) == f"id: {event['cursor']}"


def test_alembic_downgrade_and_upgrade():
    # A leaked connection holding locks must fail this test, not hang the CI job.
    env = {**os.environ, "PGOPTIONS": "-c lock_timeout=30s"}
    for step in ("downgrade base", "upgrade head"):
        subprocess.run(
            [sys.executable, "-m", "alembic", *step.split()], cwd=SERVICE_DIR, env=env, check=True, timeout=120
        )


def test_secret_is_required_outside_test_mode(monkeypatch):
    from aihub_control.config import Settings

    monkeypatch.delenv("AIHUB_SECRET_KEY", raising=False)
    monkeypatch.delenv("AIHUB_SECRET_KEY_FILE", raising=False)
    monkeypatch.setenv("AIHUB_ENV", "development")
    with pytest.raises(ValueError, match="AIHUB_SECRET_KEY"):
        Settings(database_url=DATABASE_URL, environment="development")


def _viewer_token(client):
    _, factory = get_session_factory()
    db = factory()
    db.add(User(username="viewer2", password_hash=hash_password("viewer-password"), role="viewer"))
    db.commit()
    db.close()
    login = client.post("/api/v0/auth/login", json={"username": "viewer2", "password": "viewer-password"})
    return login.json()["access_token"]


def test_session_list_respects_project_visibility(client, admin_token):
    make_project(client, admin_token, "private-a")
    make_project(client, admin_token, "shared-b", visibility="shared")
    hidden = make_session(client, admin_token, "private-a")
    visible = make_session(client, admin_token, "shared-b")
    admin_ids = {s["id"] for s in client.get("/api/v0/sessions", headers=auth(admin_token)).json()}
    assert {hidden["id"], visible["id"]} <= admin_ids
    viewer_ids = {s["id"] for s in client.get("/api/v0/sessions", headers=auth(_viewer_token(client))).json()}
    assert visible["id"] in viewer_ids and hidden["id"] not in viewer_ids
    by_project = client.get("/api/v0/sessions?project_id=shared-b", headers=auth(admin_token)).json()
    assert [s["id"] for s in by_project] == [visible["id"]]


def test_dashboard_shows_newest_events(client, admin_token):
    make_project(client, admin_token)
    session = make_session(client, admin_token)
    posted = client.post(
        f"/api/v0/sessions/{session['id']}/events",
        headers=auth(admin_token),
        json=[{"kind": "message", "payload": {"n": n}} for n in range(25)],
    ).json()
    recent = client.get("/api/v0/dashboard", headers=auth(admin_token)).json()["events"]
    assert [e["cursor"] for e in recent] == [e["cursor"] for e in posted[-20:]]


def test_cached_worker_token_still_honours_revocation(client, admin_token):
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "worker-c", "host": "local", "kind": "linux"}).json()
    headers = auth(worker["worker_token"])
    for _ in range(2):  # the second call is served from the verified-token cache
        assert client.post("/api/v0/workers/worker-c/heartbeat", headers=headers).status_code == 200
    from datetime import datetime, timezone
    from aihub_control.models import WorkerToken
    _, factory = get_session_factory()
    db = factory()
    for record in db.query(WorkerToken).filter_by(worker_id="worker-c"):
        record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.close()
    assert client.post("/api/v0/workers/worker-c/heartbeat", headers=headers).status_code in (401, 403)


def test_project_create_enqueues_mkdir_for_online_workers(client, admin_token):
    from aihub_control.models import WorkerRequest
    from sqlalchemy import select

    _, factory = get_session_factory()
    with factory() as db:
        db.add(Worker(id="worker-on", host="wsl", kind="wsl", status="online"))
        db.add(Worker(id="worker-off", host="wsl", kind="wsl", status="offline"))
        db.commit()
    response = client.post(
        "/api/v0/projects",
        headers=auth(admin_token),
        json={"id": "mk-demo", "name": "mk", "allowed_paths": ["~/projects/mk-demo"]},
    )
    assert response.status_code == 201
    # Unchanged path on update does not enqueue a second request.
    assert client.patch(
        "/api/v0/projects/mk-demo",
        headers=auth(admin_token),
        json={"id": "mk-demo", "name": "renamed", "allowed_paths": ["~/projects/mk-demo"]},
    ).status_code == 200
    with factory() as db:
        requests = list(db.scalars(select(WorkerRequest).where(WorkerRequest.kind == "mkdir")))
    assert [(r.worker_id, r.path, r.status) for r in requests] == [
        ("worker-on", "~/projects/mk-demo", "queued")
    ]


def test_events_newest_returns_the_latest_page_in_order(client, admin_token):
    make_project(client, admin_token)
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "local", "kind": "linux"})
    session = make_session(client, admin_token)
    client.post(f"/api/v0/sessions/{session['id']}/events", headers=auth(admin_token),
                json=[{"kind": "output", "payload": {"n": i}} for i in range(5)])
    page = client.get(f"/api/v0/events?session_id={session['id']}&limit=2&newest=true", headers=auth(admin_token)).json()
    assert [event["payload"]["n"] for event in page] == [3, 4]


def test_events_chat_filter_keeps_the_conversation_only(client, admin_token):
    make_project(client, admin_token)
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "local", "kind": "linux"})
    session = make_session(client, admin_token)
    client.post(f"/api/v0/sessions/{session['id']}/events", headers=auth(admin_token), json=[
        {"kind": "message", "payload": {"role": "user", "text": "вопрос"}},
        {"kind": "output", "payload": {"raw_type": "system", "text": "thinking_tokens"}},
        {"kind": "message", "payload": {"role": "assistant", "raw_type": "assistant", "text": "отв", "partial": True}},
        {"kind": "tool.call", "payload": {"name": "Bash"}},
        {"kind": "message", "payload": {"role": "assistant", "raw_type": "result", "text": "ответ"}},
        {"kind": "message", "payload": {"role": "assistant", "raw_type": "assistant", "text": "ответ"}},
    ])
    page = client.get(f"/api/v0/events?session_id={session['id']}&limit=50&newest=true&chat=true",
                      headers=auth(admin_token)).json()
    # Tool calls are part of the chat (folded into one line per run of steps); output and partials are not.
    assert [(event["kind"], event["payload"].get("text")) for event in page] == [
        ("message", "вопрос"),
        ("tool.call", None),
        ("message", "ответ"),
    ]
    activity = client.get(f"/api/v0/events?session_id={session['id']}&limit=50&newest=true&view=activity",
                          headers=auth(admin_token)).json()
    assert [event["kind"] for event in activity] == ["message", "tool.call", "message"]
    log = client.get(f"/api/v0/events?session_id={session['id']}&limit=50&newest=true&view=events",
                     headers=auth(admin_token)).json()
    assert len(log) == 5  # everything but the streamed partial


def test_event_row_without_redacted_flag_does_not_break_history(client, admin_token):
    from sqlalchemy import text
    make_project(client, admin_token)
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "local", "kind": "linux"})
    session = make_session(client, admin_token)
    _, factory = get_session_factory()
    db = factory()
    db.execute(text("insert into control.agent_events(session_id, kind, source, payload, ts) "
                    "values (:s, 'output', 'heartbeat', '{}', now())"), {"s": session["id"]})
    db.commit()
    db.close()
    response = client.get(f"/api/v0/events?session_id={session['id']}", headers=auth(admin_token))
    assert response.status_code == 200 and response.json()[-1]["redacted"] is False


def test_held_session_is_not_claimable_until_started(client, admin_token):
    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "worker-a", "host": "local", "kind": "linux"}).json()
    created = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "demo", "worker_id": "worker-a", "engine": "mock", "provider": "test", "model": "mock",
        "auth_mode": "local", "workdir": "/tmp/project", "title": "with files", "hold": True,
    })
    assert created.status_code == 200 and created.json()["status"] == "draft"
    session_id = created.json()["id"]
    assignments = client.get("/api/v0/worker-a/assignments", headers=auth(worker["worker_token"])).json()
    assert session_id not in [item["id"] for item in assignments]
    started = client.post(f"/api/v0/sessions/{session_id}/start", headers=auth(admin_token))
    assert started.status_code == 200 and started.json()["status"] == "queued"
    assignments = client.get("/api/v0/worker-a/assignments", headers=auth(worker["worker_token"])).json()
    assert session_id in [item["id"] for item in assignments]
    assert client.post(f"/api/v0/sessions/{session_id}/start", headers=auth(admin_token)).status_code == 409
