"""Project file browser: the request goes to the project's worker with the project folder and comes back once."""
import pytest

from aihub_control.auth import hash_password
from aihub_control.db import get_session_factory
from aihub_control.models import Project, User, Worker, WorkerRequest
from test_api_integration import admin_token, auth, clean_schema, client, make_project, make_session

pytestmark = pytest.mark.integration


def test_files_round_trip_to_the_sessions_worker(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "h", "kind": "linux"}).json()
    make_session(client, admin_token, worker_id="worker-a")
    _, factory = get_session_factory()
    with factory() as db:
        db.get(Worker, "worker-a").status = "online"
        db.get(Project, "demo").allowed_paths = ["/srv/demo"]
        db.commit()
    queued = client.post("/api/v0/projects/demo/files", headers=auth(admin_token), json={"op": "list", "path": ".aihub/share"})
    assert queued.status_code == 200, queued.text
    request_id = queued.json()["request_id"]
    assert client.get(f"/api/v0/files/requests/{request_id}", headers=auth(admin_token)).json() == {"status": "queued"}
    pending = client.get("/api/v0/workers/worker-a/requests/next", headers=auth(worker["worker_token"])).json()
    # The folder comes from the project record; the panel only names a path inside it.
    assert pending["kind"] == "files"
    assert pending["response"] == {"op": "list", "path": ".aihub/share", "workdir": "/srv/demo"}
    client.post(f"/api/v0/workers/worker-a/requests/{pending['id']}/response", headers=auth(worker["worker_token"]),
                json={"result": {"path": ".aihub/share", "entries": [], "share": ".aihub/share"}})
    answer = client.get(f"/api/v0/files/requests/{request_id}", headers=auth(admin_token)).json()
    assert answer == {"status": "completed", "result": {"path": ".aihub/share", "entries": [], "share": ".aihub/share"}}
    assert client.get(f"/api/v0/files/requests/{request_id}", headers=auth(admin_token)).status_code == 404
    _, factory = get_session_factory()
    with factory() as db:
        assert db.query(WorkerRequest).filter_by(kind="files").count() == 0


def test_only_the_asker_collects_and_bad_input_is_refused(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "h", "kind": "linux"})
    _, factory = get_session_factory()
    with factory() as db:
        db.get(Worker, "worker-a").status = "online"
        db.get(Project, "demo").allowed_paths = ["/srv/demo"]
        db.commit()
    url = "/api/v0/projects/demo/files"
    assert client.post(url, headers=auth(admin_token), json={"op": "write"}).status_code == 422
    assert client.post(url, headers=auth(admin_token), json={"op": "list", "workdir": "/etc"}).json()["request_id"]
    with factory() as db:  # an extra field from the panel never replaces the project's folder
        assert db.query(WorkerRequest).filter_by(kind="files").one().response["workdir"] == "/srv/demo"
    request_id = client.post(url, headers=auth(admin_token), json={"op": "list"}).json()["request_id"]
    with factory() as db:
        db.add(User(username="other", password_hash=hash_password("other-password"), role="admin"))
        db.commit()
    other = client.post("/api/v0/auth/login", json={"username": "other", "password": "other-password"}).json()["access_token"]
    assert client.get(f"/api/v0/files/requests/{request_id}", headers=auth(other)).status_code == 404


def test_a_sessions_own_folder(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "h", "kind": "linux"}).json()
    sid = make_session(client, admin_token, worker_id="worker-a")["id"]
    _, factory = get_session_factory()
    with factory() as db:
        db.get(Worker, "worker-a").status = "online"
        db.commit()
    queued = client.post(f"/api/v0/sessions/{sid}/files", headers=auth(admin_token), json={"op": "read", "path": ".aihub/share/a.png"})
    assert queued.status_code == 200, queued.text
    pending = client.get("/api/v0/workers/worker-a/requests/next", headers=auth(worker["worker_token"])).json()
    # The worker takes the session's workdir from the hub's record of the session.
    assert pending["workdir"] == "/tmp/project" and pending["response"] == {"op": "read", "path": ".aihub/share/a.png"}
