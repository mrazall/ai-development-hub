"""User scenarios end to end: hub API + a real Worker (mock engines instead of Claude/Codex).

Run before every deploy (scripts/predeploy-check.sh). Each test is one path a user takes in the panel:
a session with a file, orchestrator → executor → owner-approved merge, auto-resume after a limit, a chat.
"""
# ruff: noqa: F811
import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2 as httpx
import pytest

from aihub_control.auth import issue_scoped_token
from aihub_control.config import Settings
from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, Session, User
from aihub_control.orchestration.auto_resume import RESUME_TEXT, resume_due
from _dbenv import import_worker
from test_api_integration import admin_token, auth, clean_schema, client, live_server, make_project

Worker = import_worker()

pytestmark = pytest.mark.integration


def _setup(client, token, tmp_path: Path, project: str = "scenario") -> dict:
    make_project(client, token, project)
    body = client.get(f"/api/v0/projects/{project}", headers=auth(token)).json()
    body["allowed_paths"] = [str(tmp_path)]
    assert client.patch(f"/api/v0/projects/{project}", headers=auth(token), json=body).status_code == 200
    worker = client.post("/api/v0/workers", headers=auth(token),
                         json={"id": "scenario-worker", "host": "local", "kind": "linux"}).json()
    for profile_id, kind in (("claude-s", "claude_code_subscription"), ("codex-s", "codex_subscription")):
        assert client.post("/api/v0/accounts", headers=auth(token), json={
            "id": profile_id, "name": profile_id, "kind": kind, "worker_id": "scenario-worker",
        }).status_code == 201
    return worker


async def _run(port: int, worker_token: str, session_id: str) -> list[dict]:
    """Let the worker take the assignment and run it to the end; return the session's events."""
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
        worker = Worker(f"http://127.0.0.1:{port}", "scenario-worker", worker_token)
        assignments = (await http.get("/api/v0/scenario-worker/assignments", headers=worker.headers)).json()
        assignment = next(item for item in assignments if item["id"] == session_id)
        await asyncio.wait_for(worker.run_assignment(http, assignment), timeout=30)
        await worker._flush_events(http)
        return (await http.get(f"/api/v0/assignments/{session_id}/events", headers=worker.headers)).json()


def _texts(events: list[dict], role: str = "assistant") -> list[str]:
    return [str(e["payload"].get("text", "")) for e in events if e["kind"] == "message" and e["payload"].get("role") == role]


def test_session_with_a_file_reaches_the_agent(client, admin_token, tmp_path):
    worker = _setup(client, admin_token, tmp_path)
    created = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "scenario", "worker_id": "scenario-worker", "engine": "mock_echo_prompt", "provider": "test",
        "model": "mock", "auth_mode": "local", "workdir": str(tmp_path), "title": "с файлом", "hold": True,
    }).json()
    assert created["status"] == "draft"
    uploaded = client.post(f"/api/v0/sessions/{created['id']}/attachments", headers=auth(admin_token),
                           files={"file": ("план.md", "# План\n".encode(), "text/markdown")})
    assert uploaded.status_code == 201, uploaded.text
    client.post(f"/api/v0/sessions/{created['id']}/events", headers=auth(admin_token), json=[
        {"kind": "message", "payload": {"role": "user", "text": "Прочитай план", "attachment_ids": [uploaded.json()["id"]]}},
    ])
    assert client.post(f"/api/v0/sessions/{created['id']}/start", headers=auth(admin_token)).json()["status"] == "queued"
    with live_server() as port:
        events = asyncio.run(_run(port, worker["worker_token"], created["id"]))
    answer = "\n".join(_texts(events))
    assert "Прочитай план" in answer and "план.md" in answer  # the prompt the engine got names the file
    assert ".aihub/attachments" in answer  # downloaded next to the agent (the worker removes it afterwards)
    assert client.get(f"/api/v0/sessions/{created['id']}", headers=auth(admin_token)).json()["status"] == "completed"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _orch_token(session_id: str) -> str:
    _, factory = get_session_factory()
    db = factory()
    try:
        admin = db.query(User).filter_by(username="admin").one()
        return issue_scoped_token(admin, {"knowledge:read", f"orchestrate:{session_id}"}, settings=Settings()).access_token
    finally:
        db.close()


def test_orchestrator_executor_and_owner_approved_merge(client, admin_token, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    worker = _setup(client, admin_token, tmp_path)
    created = client.post("/api/v0/orchestrations", headers=auth(admin_token), json={
        "project_id": "scenario", "title": "Демо", "spec": "Сделай файл.", "workdir": str(repo),
        "orchestrator": {"account_profile_id": "claude-s"},
        "executors": {"count": 1, "account_profile_id": "codex-s", "model": "gpt-5.6-luna"},
        "manual_merge": True,
    })
    assert created.status_code == 201, created.text
    orchestrator_id = created.json()["session_id"]
    orch = {"Authorization": f"Bearer {_orch_token(orchestrator_id)}"}
    # The orchestrator's side (its Claude is not run here): a plan, then an executor.
    assert client.post(f"/api/v0/orchestrations/{orchestrator_id}/plan", headers=orch,
                       json={"steps": [{"title": "Создать файл", "status": "in_progress"}]}).status_code == 200
    spawned = client.post(f"/api/v0/orchestrations/{orchestrator_id}/executors", headers=orch,
                          json={"title": "Файл", "prompt": "напиши файл"}).json()
    _, factory = get_session_factory()
    db = factory()
    try:
        db.get(Session, spawned["id"]).engine = "mock_write"  # stands in for Codex
        db.commit()
    finally:
        db.close()

    with live_server() as port:
        events = asyncio.run(_run(port, worker["worker_token"], spawned["id"]))
        branch = spawned["branch"]
        assert "mock-output.txt" in _git(repo, "show", "--stat", "--format=", branch)  # the worker committed it
        # Found live: the orchestrator saw «completed» before the commit and moved files by hand, and the commit
        # note was lost (it reused event index 0). The note is in the feed, before the final status.
        note = next(e for e in events if "закоммичены" in str(e["payload"].get("text", "")))
        done = next(e for e in events if e["kind"] == "session.status" and e["payload"].get("status") == "completed")
        assert note["cursor"] < done["cursor"]
        asked = client.post(f"/api/v0/orchestrations/{orchestrator_id}/executors/{spawned['id']}/merge-request",
                            headers=orch, json={"summary": "файл готов"})
        assert asked.status_code == 200 and asked.json()["merge"]["state"] == "requested"
        view = client.get(f"/api/v0/sessions/{orchestrator_id}/orchestration", headers=auth(admin_token)).json()
        assert view["manual_merge"] is True and view["plan"][0]["title"] == "Создать файл"
        assert view["executors"][0]["merge"]["state"] == "requested"
        assert client.post(f"/api/v0/sessions/{spawned['id']}/merge/accept", headers=auth(admin_token)).status_code == 200

        async def merge():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                await Worker(f"http://127.0.0.1:{port}", "scenario-worker", worker["worker_token"]).service_workspace_request(http)

        asyncio.run(merge())
    assert (repo / "mock-output.txt").exists() and _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    view = client.get(f"/api/v0/sessions/{orchestrator_id}/orchestration", headers=auth(admin_token)).json()
    assert view["executors"][0]["merge"]["state"] == "merged"
    db = factory()
    try:
        told = [e.payload.get("text", "") for e in db.query(AgentEvent).filter_by(session_id=orchestrator_id, kind="message")]
        assert any("принял слияние" in text for text in told)
    finally:
        db.close()


def test_limit_hit_is_resumed_after_the_reset(client, admin_token, tmp_path):
    worker = _setup(client, admin_token, tmp_path)
    created = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "scenario", "worker_id": "scenario-worker", "engine": "mock_limit", "provider": "test",
        "model": "mock", "auth_mode": "local", "workdir": str(tmp_path), "title": "упрётся в лимит",
    }).json()
    client.post(f"/api/v0/sessions/{created['id']}/events", headers=auth(admin_token),
                json=[{"kind": "message", "payload": {"role": "user", "text": "работай"}}])
    with live_server() as port:
        asyncio.run(_run(port, worker["worker_token"], created["id"]))
    failed = client.get(f"/api/v0/sessions/{created['id']}", headers=auth(admin_token)).json()
    assert failed["status"] == "failed" and failed["resume_at"]
    _, factory = get_session_factory()
    db = factory()
    try:
        assert resume_due(db, datetime.now(timezone.utc) + timedelta(days=2)) == 1
        # The same session continues (no new session), on the same agent conversation, with the resume note.
        assert db.query(Session).filter_by(parent_session_id=created["id"]).count() == 0
        resumed = db.get(Session, created["id"])
        assert resumed.status == "queued" and resumed.engine_session_ref == "mock-ref" and resumed.resume_at is None
        texts = [e.payload["text"] for e in db.query(AgentEvent).filter_by(session_id=created["id"], kind="message")
                 .order_by(AgentEvent.cursor) if e.payload.get("role") == "user"]
        assert texts[-1] == RESUME_TEXT
    finally:
        db.close()


def test_chat_answers_and_continues(client, admin_token, tmp_path, monkeypatch):
    monkeypatch.setenv("AIHUB_CHAT_ENGINE", "mock_echo_prompt")
    monkeypatch.setenv("HOME", str(tmp_path))  # chats work in ~/.aihub/chats/<id>
    worker = _setup(client, admin_token, tmp_path)
    chat = client.post("/api/v0/chats", headers=auth(admin_token), json={"text": "Привет", "account_profile_id": "claude-s"})
    assert chat.status_code == 201, chat.text
    with live_server() as port:
        asyncio.run(_run(port, worker["worker_token"], chat.json()["id"]))
        _, factory = get_session_factory()
        db = factory()
        try:
            db.get(Session, chat.json()["id"]).engine_session_ref = "mock-ref"  # Claude reports it; the mock does not
            db.commit()
        finally:
            db.close()
        follow = client.post(f"/api/v0/sessions/{chat.json()['id']}/continue", headers=auth(admin_token),
                             json={"text": "Ещё вопрос"})
        assert follow.status_code == 201, follow.text
        asyncio.run(_run(port, worker["worker_token"], follow.json()["id"]))
    messages = client.get(f"/api/v0/chats/{chat.json()['id']}", headers=auth(admin_token)).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert "Ещё вопрос" in messages[-1]["text"]
