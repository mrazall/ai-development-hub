# ruff: noqa: F811

import asyncio

import httpx2 as httpx
import pytest

# Cross-component test: needs packages/agent-adapters (installed by the integration workflow, not the unit job).
Worker = pytest.importorskip("aihub_agents.worker").Worker

from test_api_integration import admin_token, auth, clean_schema, client, live_server, make_project

pytestmark = pytest.mark.integration


def _run(coro):
    return asyncio.run(coro)


def _create_session(client, token, worker_id, engine):
    response = client.post(
        "/api/v0/sessions",
        headers=auth(token),
        json={
            "project_id": "demo",
            "worker_id": worker_id,
            "engine": engine,
            "provider": "test",
            "model": "mock",
            "auth_mode": "local",
            "workdir": "/tmp/project",
            "title": "Run the test task",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_real_worker_delivers_message_and_stops_assignment(client, admin_token, clean_schema):
    make_project(client, admin_token)
    project = client.get("/api/v0/projects/demo", headers=auth(admin_token)).json()
    project["allowed_paths"] = ["/tmp"]
    assert client.patch("/api/v0/projects/demo", headers=auth(admin_token), json=project).status_code == 200
    worker_response = client.post(
        "/api/v0/workers",
        headers=auth(admin_token),
        json={"id": "worker-a", "host": "local", "kind": "local"},
    )
    assert worker_response.status_code == 200
    worker_data = worker_response.json()
    echo_session = _create_session(client, admin_token, "worker-a", "mock_echo")
    hanging_session = _create_session(client, admin_token, "worker-a", "mock_hang")

    with live_server() as port:
        async def exercise_worker():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                worker = Worker(
                    f"http://127.0.0.1:{port}", "worker-a", worker_data["worker_token"]
                )
                assignments = await http.get(
                    "/api/v0/worker-a/assignments",
                    headers=worker.headers,
                )
                assert assignments.status_code == 200
                echo_assignment = next(
                    item for item in assignments.json() if item["id"] == echo_session["id"]
                )
                task = asyncio.create_task(worker.run_assignment(http, echo_assignment))
                for _ in range(500):  # a loaded test box can take over a second to reach starting
                    state = await http.get(
                        f"/api/v0/assignments/{echo_session['id']}", headers=worker.headers
                    )
                    if state.json()["status"] == "starting":
                        break
                    await asyncio.sleep(0.01)
                client.post(
                    f"/api/v0/sessions/{echo_session['id']}/events",
                    headers=auth(admin_token),
                    json=[
                        {
                            "kind": "message",
                            "source": "native",
                            "client_event_id": "user-message-1",
                            "payload": {"role": "user", "text": "hello from GUI"},
                        }
                    ],
                )
                await asyncio.wait_for(task, timeout=15)

                events = (
                    await http.get(
                        f"/api/v0/assignments/{echo_session['id']}/events",
                        headers=worker.headers,
                    )
                ).json()
                assert any(
                    event["payload"].get("text") == "echo: hello from GUI" for event in events
                )

                stop_assignment = next(
                    item for item in (await http.get(
                        "/api/v0/worker-a/assignments", headers=worker.headers
                    )).json() if item["id"] == hanging_session["id"]
                )
                stop_task = asyncio.create_task(worker.run_assignment(http, stop_assignment))
                for _ in range(100):
                    state = await http.get(
                        f"/api/v0/assignments/{hanging_session['id']}", headers=worker.headers
                    )
                    if state.json()["status"] == "starting":
                        break
                    await asyncio.sleep(0.01)
                client.post(
                    f"/api/v0/sessions/{hanging_session['id']}/stop",
                    headers=auth(admin_token),
                )
                await asyncio.wait_for(stop_task, timeout=5)

        _run(exercise_worker())

    assert client.get(
        f"/api/v0/sessions/{echo_session['id']}", headers=auth(admin_token)
    ).json()["status"] == "completed"
    assert client.get(
        f"/api/v0/sessions/{hanging_session['id']}", headers=auth(admin_token)
    ).json()["status"] == "failed"


def test_worker_restart_marks_starting_and_running_sessions_failed(client, admin_token, clean_schema):
    make_project(client, admin_token)
    worker = client.post(
        "/api/v0/workers", headers=auth(admin_token),
        json={"id": "worker-restart", "host": "local", "kind": "linux"},
    ).json()
    first = _create_session(client, admin_token, "worker-restart", "mock_hang")
    second = _create_session(client, admin_token, "worker-restart", "mock_hang")
    for session in (first, second):
        claimed = client.post(f"/api/v0/assignments/{session['id']}/claim", headers=auth(worker["worker_token"]))
        assert "branch" in claimed.json()  # executors need it for `git worktree add -b`
    from aihub_control.db import get_session_factory
    from aihub_control.models import Session
    _, factory = get_session_factory()
    db = factory()
    db.get(Session, first["id"]).status = "running"
    db.commit()
    db.close()

    response = client.post(
        "/api/v0/workers/worker-restart/recover", headers=auth(worker["worker_token"])
    )
    assert response.status_code == 200
    assert response.json() == {"failed": 2}
    assert all(
        client.get(f"/api/v0/sessions/{session['id']}", headers=auth(admin_token)).json()["status"] == "failed"
        for session in (first, second)
    )
