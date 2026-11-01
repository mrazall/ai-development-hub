"""Agent instructions: the hub queues requests for a worker, hands the answer back once and keeps no text."""
import pytest

from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, AuditLog, User, WorkerRequest
from aihub_control.auth import hash_password
from test_api_integration import admin_token, auth, clean_schema, client, make_session

pytestmark = pytest.mark.integration
MARK = "SECRET-MARKER-123"


def _project(api, token):
    response = api.post("/api/v0/projects", headers=auth(token), json={
        "id": "demo", "name": "demo", "visibility": "shared", "allowed_paths": ["/tmp/project"]})
    assert response.status_code == 201


def _worker(api, token):
    return api.post("/api/v0/workers", headers=auth(token), json={"id": "worker-a", "host": "h", "kind": "linux"}).json()


def _serve(api, worker, answer):
    """Play the worker: take the next request, check what it was given, answer it."""
    request = api.get("/api/v0/workers/worker-a/requests/next", headers=auth(worker["worker_token"])).json()
    api.post(f"/api/v0/workers/worker-a/requests/{request['id']}/response",
                headers=auth(worker["worker_token"]), json=answer)
    return request


def _login(api, role):
    _, factory = get_session_factory()
    db = factory()
    db.add(User(username=role, password_hash=hash_password(f"{role}-password"), role=role))
    db.commit()
    db.close()
    return api.post("/api/v0/auth/login", json={"username": role, "password": f"{role}-password"}).json()["access_token"]


def test_project_file_round_trip_keeps_no_text(client, admin_token):  # noqa: F811
    _project(client, admin_token)
    worker = _worker(client, admin_token)
    make_session(client, admin_token, worker_id="worker-a")
    queued = client.post("/api/v0/projects/demo/instructions", headers=auth(admin_token),
                         json={"op": "write", "path": "AGENTS.md", "content": MARK, "base_sha256": "a" * 64}).json()
    assert queued["worker_id"] == "worker-a"
    assert client.get(f"/api/v0/instructions/requests/{queued['request_id']}", headers=auth(admin_token)).json() == {
        "status": "queued"}
    request = _serve(client, worker, {"result": {"commit": "abc1234", "snapshot": None, "backup": None, "sha256": "b" * 64}})
    params = request["response"]
    assert (params["op"], params["scope"], params["path"], params["project_root"]) == (
        "write", "project", "AGENTS.md", "/tmp/project")
    answer = client.get(f"/api/v0/instructions/requests/{queued['request_id']}", headers=auth(admin_token)).json()
    assert answer == {"status": "completed", "result": {"commit": "abc1234", "snapshot": None, "backup": None, "sha256": "b" * 64}}
    # Given once, then gone; the audit says who changed which file, without the text.
    assert client.get(f"/api/v0/instructions/requests/{queued['request_id']}", headers=auth(admin_token)).status_code == 404
    _, factory = get_session_factory()
    db = factory()
    audit = db.query(AuditLog).filter_by(action="instructions.change").one()
    assert audit.target == "worker-a:AGENTS.md" and audit.details["commit"] == "abc1234"
    assert MARK not in str(audit.details)
    assert db.query(WorkerRequest).filter_by(kind="instructions").count() == 0
    assert all(MARK not in str(event.payload) for event in db.query(AgentEvent))
    db.close()


def test_conflict_and_refusals(client, admin_token):  # noqa: F811
    _project(client, admin_token)
    worker = _worker(client, admin_token)
    url = "/api/v0/projects/demo/instructions"
    for path in ("../../.bashrc", "README.md", ".claude/skills/Bad/SKILL.md"):
        assert client.post(url, headers=auth(admin_token), json={"op": "read", "path": path}).status_code == 422
    assert client.post(url, headers=auth(admin_token), json={"op": "backups", "path": "AGENTS.md"}).status_code == 422
    too_big = client.post(url, headers=auth(admin_token), json={"op": "write", "path": "AGENTS.md", "content": "x" * (256 * 1024 + 1)})
    assert too_big.status_code == 413
    queued = client.post(url, headers=auth(admin_token), json={"op": "read", "path": "AGENTS.md"}).json()
    _serve(client, worker, {"error": "conflict: файл изменился на воркере"})
    answer = client.get(f"/api/v0/instructions/requests/{queued['request_id']}", headers=auth(admin_token)).json()
    assert answer == {"status": "failed", "error": "файл изменился на воркере", "code": 409}


def test_roles(client, admin_token):  # noqa: F811
    _project(client, admin_token)
    _worker(client, admin_token)
    viewer = _login(client, "viewer")
    assert client.post("/api/v0/projects/demo/instructions", headers=auth(viewer),
                       json={"op": "write", "path": "AGENTS.md", "content": "x"}).status_code in {403, 404}
    # The worker's shared files act on every account there: administrators only.
    assert client.post("/api/v0/workers/worker-a/instructions", headers=auth(viewer), json={"op": "list"}).status_code == 403
    queued = client.post("/api/v0/workers/worker-a/instructions", headers=auth(admin_token),
                         json={"op": "read", "path": "claude/CLAUDE.md"}).json()
    # Another user cannot collect someone else's answer.
    assert client.get(f"/api/v0/instructions/requests/{queued['request_id']}", headers=auth(viewer)).status_code == 404
