# ruff: noqa: F811
"""Integration coverage for the accounts UX contract.

These tests deliberately use the public HTTP API for both user and worker
operations; direct database writes only model an already exhausted session.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2 as httpx
import pytest

from aihub_control.db import get_session_factory
from aihub_control.auth import hash_password
from aihub_control.models import AgentEvent, Session, User, Worker as WorkerRow, WorkerRequest
from aihub_control.orchestration.auto_resume import resume_due
from aihub_control.routers import sessions as sessions_router
from _dbenv import import_worker
from test_api_integration import admin_token, auth, clean_schema, client, live_server, make_project

AgentWorker = import_worker()

pytestmark = pytest.mark.integration


def register_worker(client, token, worker_id):
    response = client.post("/api/v0/workers", headers=auth(token), json={
        "id": worker_id, "host": "local", "kind": "linux",
    })
    assert response.status_code == 200, response.text
    return response.json()


def create_account(client, token, account_id, worker_id, kind="claude_code_subscription", **extra):
    response = client.post("/api/v0/accounts", headers=auth(token), json={
        "id": account_id, "name": account_id, "kind": kind, "worker_id": worker_id, **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_next_id_and_subscription_defaults(client, admin_token):
    worker = register_worker(client, admin_token, "one-worker")
    assert client.get("/api/v0/accounts/next-id?kind=claude_code_subscription",
                      headers=auth(admin_token)).json() == {"id": "claude-1", "name": "Claude 1"}
    created = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "kind": "claude_code_subscription",
    })
    assert created.status_code == 201, created.text
    assert created.json()["id"] == "claude-1"
    assert created.json()["worker_id"] == "one-worker"

    # One online worker wins even when another registered worker is offline.
    other = register_worker(client, admin_token, "offline-worker")
    db_factory = get_session_factory()[1]
    db = db_factory()
    db.get(WorkerRow, other["id"]).status = "offline"
    db.commit()
    db.close()
    selected = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "kind": "codex_subscription",
    })
    assert selected.status_code == 201, selected.text
    assert selected.json()["worker_id"] == worker["id"]

    register_worker(client, admin_token, "two-worker")
    response = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "kind": "codex_subscription",
    })
    assert response.status_code == 422
    assert "several workers" in response.text


def test_next_id_reserves_deleted_ids_and_duplicate_create_is_conflict(client, admin_token):
    worker = register_worker(client, admin_token, "id-worker")
    created = create_account(client, admin_token, "claude-1", worker["id"])
    assert client.delete(f"/api/v0/accounts/{created['id']}", headers=auth(admin_token)).status_code == 204
    next_id = client.get("/api/v0/accounts/next-id?kind=claude_code_subscription",
                         headers=auth(admin_token))
    assert next_id.json() == {"id": "claude-2", "name": "Claude 2"}
    reserved = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-1", "name": "Claude 1", "kind": "claude_code_subscription",
        "worker_id": worker["id"],
    })
    assert reserved.status_code == 409

    duplicate = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-2", "name": "Claude 2", "kind": "claude_code_subscription",
        "worker_id": worker["id"],
    })
    assert duplicate.status_code == 201
    raced = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-2", "name": "Claude 2", "kind": "claude_code_subscription",
        "worker_id": worker["id"],
    })
    assert raced.status_code == 409
    assert "already exists" in raced.text


def test_found_logins_are_scoped_and_adoption_queues_request(client, admin_token):
    first = register_worker(client, admin_token, "found-one")
    register_worker(client, admin_token, "found-two")
    payload = {"logins": [{"engine": "claude", "identity": "user@example.com"}]}
    assert client.post("/api/v0/workers/found-one/found-logins", headers=auth(first["worker_token"]),
                       json=payload).status_code == 200
    assert client.post("/api/v0/workers/found-two/found-logins", headers=auth(first["worker_token"]),
                       json=payload).status_code == 403
    found = client.get("/api/v0/accounts/found-logins", headers=auth(admin_token))
    assert found.status_code == 200
    assert found.json() == [{"worker_id": "found-one", "engine": "claude",
                             "identity": "user@example.com", "kind": "claude_code_subscription"}]

    adopted = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "kind": "claude_code_subscription", "worker_id": "found-one", "adopt_found_login": True,
    })
    assert adopted.status_code == 201, adopted.text
    request = client.get("/api/v0/workers/found-one/requests/next", headers=auth(first["worker_token"])).json()
    assert request["kind"] == "account_adopt_login"
    assert request["response"] == {"account_id": adopted.json()["id"], "engine": "claude"}


def test_identity_duplicates_login_watch_and_login_commands(client, admin_token):
    worker = register_worker(client, admin_token, "identity-worker")
    first = create_account(client, admin_token, "claude-a", "identity-worker")
    second = create_account(client, admin_token, "claude-b", "identity-worker")
    for account_id in (first["id"], second["id"]):
        status = client.post(f"/api/v0/accounts/{account_id}/status", headers=auth(worker["worker_token"]),
                             json={"status": "connected", "identity": "same@example.com"})
        assert status.status_code == 200, status.text
    listed = {item["id"]: item for item in client.get("/api/v0/accounts", headers=auth(admin_token)).json()}
    assert listed["claude-a"]["identity"] == "same@example.com"
    assert listed["claude-a"]["duplicate_of"] == ["claude-b"]
    assert listed["claude-b"]["duplicate_of"] == ["claude-a"]

    started = client.post("/api/v0/accounts/claude-a/login-started", headers=auth(admin_token))
    assert started.status_code == 202
    worker_accounts = client.get("/api/v0/workers/identity-worker/accounts",
                                headers=auth(worker["worker_token"])).json()
    watched = next(item for item in worker_accounts if item["id"] == "claude-a")
    assert watched["login_watch_until"]
    claude = client.get("/api/v0/accounts/claude-a/login-command", headers=auth(admin_token)).json()
    assert claude["shell"] == "CLAUDE_CONFIG_DIR=~/.aihub/accounts/claude-a/claude claude auth login"
    assert claude["argv"] == ["claude", "auth", "login"]
    codex = create_account(client, admin_token, "codex-a", "identity-worker", "codex_subscription")
    command = client.get(f"/api/v0/accounts/{codex['id']}/login-command", headers=auth(admin_token)).json()
    assert command["shell"] == "CODEX_HOME=~/.aihub/accounts/codex-a/codex codex login --device-auth"
    assert command["argv"] == ["codex", "login", "--device-auth"]


def test_accounts_mutations_are_admin_only_and_identity_input_is_bounded(client, admin_token):
    worker = register_worker(client, admin_token, "security-worker")
    other_worker = register_worker(client, admin_token, "security-other-worker")
    account = create_account(client, admin_token, "security-account", worker["id"])
    other_account = create_account(client, admin_token, "security-other-account", other_worker["id"])
    make_project(client, admin_token, "security-project")
    session = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "security-project", "worker_id": worker["id"], "engine": "claude_code",
        "provider": "test", "model": "mock", "auth_mode": "subscription", "workdir": "/tmp",
        "account_profile_id": account["id"],
    }).json()
    db_factory = get_session_factory()[1]
    db = db_factory()
    db.get(Session, session["id"]).resume_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    db.add(User(username="accounts-viewer", password_hash=hash_password("viewer-password"), role="viewer"))
    db.commit()
    db.close()
    viewer_login = client.post("/api/v0/auth/login", json={
        "username": "accounts-viewer", "password": "viewer-password"
    })
    viewer = auth(viewer_login.json()["access_token"])

    assert client.get("/api/v0/accounts/next-id?kind=claude_code_subscription", headers=viewer).status_code == 403
    assert client.post("/api/v0/accounts", headers=viewer, json={"kind": "claude_code_subscription"}).status_code == 403
    assert client.post(f"/api/v0/accounts/{account['id']}/login-started", headers=viewer).status_code == 403
    assert client.get(f"/api/v0/accounts/{account['id']}/login-command", headers=viewer).status_code == 403
    assert client.post(f"/api/v0/sessions/{session['id']}/continue-on-account", headers=viewer,
                       json={"account_profile_id": account["id"]}).status_code == 403
    assert client.delete(f"/api/v0/accounts/{account['id']}", headers=viewer).status_code == 403

    too_long = client.post(f"/api/v0/accounts/{account['id']}/status", headers=auth(worker["worker_token"]),
                           json={"status": "connected", "identity": "x" * 201})
    control = client.post(f"/api/v0/accounts/{account['id']}/status", headers=auth(worker["worker_token"]),
                          json={"status": "connected", "identity": "ok\nnope"})
    assert too_long.status_code == control.status_code == 422
    unknown_engine = client.post(f"/api/v0/workers/{worker['id']}/found-logins",
                                 headers=auth(worker["worker_token"]),
                                 json={"logins": [{"engine": "other", "identity": "x"}]})
    assert unknown_engine.status_code == 422
    foreign_status = client.post(f"/api/v0/accounts/{other_account['id']}/status",
                                 headers=auth(worker["worker_token"]),
                                 json={"status": "connected", "identity": "other@example.com"})
    assert foreign_status.status_code == 403
    non_subscription = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "security-api", "name": "security-api", "kind": "openai_api", "worker_id": worker["id"],
    })
    assert non_subscription.status_code == 201
    assert client.get(f"/api/v0/accounts/{non_subscription.json()['id']}/login-command",
                      headers=auth(admin_token)).status_code == 409


def test_delete_guards_sessions_and_queues_worker_request(client, admin_token):
    worker = register_worker(client, admin_token, "delete-worker")
    account = create_account(client, admin_token, "delete-me", "delete-worker")
    make_project(client, admin_token, "delete-project")
    session = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "delete-project", "worker_id": "delete-worker", "engine": "mock_echo",
        "provider": "test", "model": "mock", "auth_mode": "local", "workdir": "/tmp",
        "account_profile_id": account["id"],
    }).json()
    assert client.delete(f"/api/v0/accounts/{account['id']}", headers=auth(admin_token)).status_code == 409
    db_factory = get_session_factory()[1]
    db = db_factory()
    db.get(Session, session["id"]).status = "completed"
    db.get(Session, session["id"]).resume_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    db.close()
    assert client.delete(f"/api/v0/accounts/{account['id']}", headers=auth(admin_token)).status_code == 409
    db = db_factory()
    db.delete(db.get(Session, session["id"]))
    db.get(WorkerRow, "delete-worker").status = "offline"
    db.commit()
    db.close()
    assert client.delete(f"/api/v0/accounts/{account['id']}", headers=auth(admin_token)).status_code == 204
    request = client.get("/api/v0/workers/delete-worker/requests/next",
                         headers=auth(worker["worker_token"])).json()
    assert request["kind"] == "account_delete" and request["response"]["account_id"] == "delete-me"


def test_auto_resume_never_changes_account_profile(client, admin_token):
    worker = register_worker(client, admin_token, "auto-resume-worker")
    account = create_account(client, admin_token, "auto-resume-account", worker["id"], "codex_subscription")
    make_project(client, admin_token, "auto-resume-project")
    created = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "auto-resume-project", "worker_id": worker["id"], "engine": "codex",
        "provider": "test", "model": "mock", "auth_mode": "subscription", "workdir": "/tmp",
        "account_profile_id": account["id"],
    }).json()
    db_factory = get_session_factory()[1]
    db = db_factory()
    session = db.get(Session, created["id"])
    session.status = "failed"
    session.resume_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.engine_session_ref = "provider-conversation"
    assert resume_due(db, datetime.now(timezone.utc)) == 1
    assert session.account_profile_id == account["id"]
    assert session.status == "queued"
    db.close()


def test_alternatives_and_continue_on_account_summary_mode(client, admin_token, monkeypatch):
    worker = register_worker(client, admin_token, "switch-worker")
    current = create_account(client, admin_token, "switch-a", "switch-worker", "codex_subscription")
    alternative = create_account(client, admin_token, "switch-b", "switch-worker", "codex_subscription")
    empty_alternative = create_account(client, admin_token, "switch-c", "switch-worker", "codex_subscription")
    disabled = create_account(client, admin_token, "switch-disabled", "switch-worker", "codex_subscription")
    register_worker(client, admin_token, "other-worker")
    foreign = create_account(client, admin_token, "switch-foreign", "other-worker", "codex_subscription")
    assert client.post(f"/api/v0/accounts/{disabled['id']}/disable", headers=auth(admin_token)).status_code == 200
    make_project(client, admin_token, "switch-project")
    session = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "switch-project", "worker_id": "switch-worker", "engine": "codex",
        "provider": "test", "model": "mock", "auth_mode": "subscription", "workdir": "/tmp",
        "account_profile_id": current["id"],
    }).json()
    captured_at = datetime.now(timezone.utc).replace(microsecond=0)
    saved_limits = {
        "captured_at": captured_at.isoformat(),
        "windows": [
            {"kind": "five_hour", "used_percent": 37.5, "resets_at": 1_800_000_000},
            {"kind": "seven_day", "used_percent": 12.0, "resets_at": 1_800_500_000},
        ],
        "status": "ok",
    }
    captured = client.post(f"/api/v0/accounts/{alternative['id']}/limits",
                           headers=auth(worker["worker_token"]), json=saved_limits)
    assert captured.status_code == 204, captured.text
    all_limits = client.get("/api/v0/limits", headers=auth(admin_token))
    assert all_limits.status_code == 200, all_limits.text
    expected_limits = next(item for item in all_limits.json() if item["account_id"] == alternative["id"])
    alternatives = client.get(f"/api/v0/sessions/{session['id']}/alternative-accounts",
                               headers=auth(admin_token))
    assert alternatives.status_code == 200
    listed_alternatives = alternatives.json()
    assert [item["account"]["id"] for item in listed_alternatives] == [alternative["id"], empty_alternative["id"]]
    assert listed_alternatives[0]["limits"] == expected_limits
    assert listed_alternatives[1]["limits"] is None
    assert client.post(f"/api/v0/sessions/{session['id']}/continue-on-account", headers=auth(admin_token),
                       json={"account_profile_id": alternative["id"]}).status_code == 409
    db_factory = get_session_factory()[1]
    db = db_factory()
    db_session = db.get(Session, session["id"])
    db_session.status = "failed"
    db_session.resume_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    db.add(AgentEvent(session_id=db_session.id, kind="message", source="native",
                      payload={"role": "assistant", "text": "previous answer /home/dev/.aihub/accounts/switch-a/claude/.credentials.json token=sk-secret-value"}))
    db.commit()
    db.close()
    assert client.post(f"/api/v0/sessions/{session['id']}/continue-on-account", headers=auth(admin_token),
                       json={"account_profile_id": foreign["id"]}).status_code == 409
    monkeypatch.setattr(sessions_router, "CROSS_ACCOUNT_RESUME_MODE", "summary")
    switched = client.post(f"/api/v0/sessions/{session['id']}/continue-on-account", headers=auth(admin_token),
                           json={"account_profile_id": alternative["id"]})
    assert switched.status_code == 200, switched.text
    assert switched.json()["account_profile_id"] == alternative["id"]
    db = db_factory()
    db_session = db.get(Session, session["id"])
    assert db_session.resume_at is None and db_session.account_profile_id == alternative["id"]
    event = db.query(AgentEvent).filter_by(session_id=session["id"], kind="session.account_switched").one()
    assert event.payload == {"from": current["id"], "to": alternative["id"], "resume_mode": "summary"}
    continuation = db.query(AgentEvent).filter_by(session_id=session["id"], kind="message").order_by(AgentEvent.cursor.desc()).first()
    assert ".credentials.json" not in continuation.payload["text"]
    assert "sk-secret-value" not in continuation.payload["text"]
    assert "/home/dev/.aihub/accounts" not in continuation.payload["text"]
    db.close()


def test_worker_request_kinds_are_bounded_and_events_do_not_contain_secrets():
    assert WorkerRequest.__table__.c.kind.type.length <= 32
    assert "token" not in str(AgentEvent.__table__.columns).lower()


def test_mock_worker_account_lifecycle(client, admin_token):
    worker = register_worker(client, admin_token, "mock-account-worker")
    assert client.post(f"/api/v0/workers/{worker['id']}/found-logins",
                       headers=auth(worker["worker_token"]),
                       json={"logins": [{"engine": "claude", "identity": "mock@example.com"}]}).status_code == 200
    created = client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "kind": "claude_code_subscription", "worker_id": worker["id"], "adopt_found_login": True,
    })
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]
    request = client.get(f"/api/v0/workers/{worker['id']}/requests/next",
                         headers=auth(worker["worker_token"])).json()
    assert request["kind"] == "account_adopt_login"
    assert client.post(f"/api/v0/workers/{worker['id']}/requests/{request['id']}/response",
                       headers=auth(worker["worker_token"]),
                       json={"result": {"copied": [".credentials.json", ".claude.json"]}}).status_code == 200
    status = client.post(f"/api/v0/accounts/{account_id}/status", headers=auth(worker["worker_token"]),
                         json={"status": "connected", "identity": "mock@example.com"})
    assert status.status_code == 200 and status.json()["identity"] == "mock@example.com"
    assert client.delete(f"/api/v0/accounts/{account_id}", headers=auth(admin_token)).status_code == 204
    deletion = client.get(f"/api/v0/workers/{worker['id']}/requests/next",
                          headers=auth(worker["worker_token"])).json()
    assert deletion["kind"] == "account_delete" and deletion["path"] == account_id


def _fake_cli(bin_dir: Path, name: str, output: str, returncode: int = 0) -> None:
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' {output!r}\nexit {returncode}\n", encoding="utf-8")
    script.chmod(0o755)


async def _worker_check_and_request(port: int, worker_id: str, token: str, request: bool = False) -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
        worker = AgentWorker(f"http://127.0.0.1:{port}", worker_id, token)
        await worker.check_account_statuses(http)
        if request:
            await worker.service_workspace_request(http)


def test_real_worker_claude_found_adopt_status_and_delete(client, admin_token, tmp_path, monkeypatch):
    """Exercise the actual adapter worker through the public hub HTTP API."""
    home = tmp_path / "home"
    claude_home = home / ".claude"
    bin_dir = tmp_path / "bin"
    claude_home.mkdir(parents=True)
    bin_dir.mkdir()
    (claude_home / ".credentials.json").write_text('{"fake": "credential"}', encoding="utf-8")
    (claude_home / ".claude.json").write_text('{"fake": "state"}', encoding="utf-8")
    _fake_cli(
        bin_dir,
        "claude",
        '{"analyticsDisabled":false,"apiProvider":"firstParty",'
        '"authMethod":"claude.ai","configDirectory":"/tmp/claude",'
        '"email":"claude@example.com","loggedIn":true,"orgId":"org-test",'
        '"orgName":"Example Org","projectsDirectory":"/tmp/projects",'
        '"subscriptionType":"max"}',
        returncode=0,
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    worker = register_worker(client, admin_token, "real-claude-worker")
    with live_server() as port:
        asyncio.run(_worker_check_and_request(port, worker["id"], worker["worker_token"]))
        found = client.get("/api/v0/accounts/found-logins", headers=auth(admin_token))
        assert found.status_code == 200
        assert found.json() == [{"worker_id": worker["id"], "engine": "claude",
                                 "identity": "claude@example.com",
                                 "kind": "claude_code_subscription"}]

        created = client.post("/api/v0/accounts", headers=auth(admin_token), json={
            "kind": "claude_code_subscription", "worker_id": worker["id"], "adopt_found_login": True,
        })
        assert created.status_code == 201, created.text
        account_id = created.json()["id"]
        asyncio.run(_worker_check_and_request(port, worker["id"], worker["worker_token"], request=True))

        profile = home / ".aihub" / "accounts" / account_id / "claude"
        assert (profile / ".credentials.json").read_text(encoding="utf-8") == '{"fake": "credential"}'
        assert (profile / ".claude.json").read_text(encoding="utf-8") == '{"fake": "state"}'
        account = client.get(f"/api/v0/accounts/{account_id}", headers=auth(admin_token)).json()
        assert account["status"] == "connected"
        assert account["identity"] == "claude@example.com"

        assert client.delete(f"/api/v0/accounts/{account_id}", headers=auth(admin_token)).status_code == 204
        asyncio.run(_worker_check_and_request(port, worker["id"], worker["worker_token"], request=True))
        assert not profile.parent.exists()


def test_real_worker_codex_found_adopt_status_and_delete(client, admin_token, tmp_path, monkeypatch):
    home = tmp_path / "home"
    codex_home = home / ".codex"
    bin_dir = tmp_path / "bin"
    codex_home.mkdir(parents=True)
    bin_dir.mkdir()
    (codex_home / "auth.json").write_text('{"fake": "credential"}', encoding="utf-8")
    _fake_cli(bin_dir, "codex", "Logged in using ChatGPT", returncode=0)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    worker = register_worker(client, admin_token, "real-codex-worker")
    with live_server() as port:
        asyncio.run(_worker_check_and_request(port, worker["id"], worker["worker_token"]))
        found = client.get("/api/v0/accounts/found-logins", headers=auth(admin_token)).json()
        assert {item["engine"] for item in found} == {"codex"}
        assert found[0]["identity"] == "Logged in using ChatGPT"
        created = client.post("/api/v0/accounts", headers=auth(admin_token), json={
            "kind": "codex_subscription", "worker_id": worker["id"], "adopt_found_login": True,
        })
        assert created.status_code == 201, created.text
        account_id = created.json()["id"]
        asyncio.run(_worker_check_and_request(port, worker["id"], worker["worker_token"], request=True))
        profile = home / ".aihub" / "accounts" / account_id / "codex"
        assert (profile / "auth.json").read_text(encoding="utf-8") == '{"fake": "credential"}'
        account = client.get(f"/api/v0/accounts/{account_id}", headers=auth(admin_token)).json()
        assert account["status"] == "connected" and account["identity"] == "Logged in using ChatGPT"
        assert client.delete(f"/api/v0/accounts/{account_id}", headers=auth(admin_token)).status_code == 204
        asyncio.run(_worker_check_and_request(port, worker["id"], worker["worker_token"], request=True))
        assert not profile.parent.exists()


def test_real_worker_continue_on_account_after_resume_at(client, admin_token, tmp_path, monkeypatch):
    # The real worker validates the assignment workdir against the project's allowlist before
    # constructing the mock adapter. Keep the profile and workdir inside this test's sandbox.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    worker = register_worker(client, admin_token, "real-resume-worker")
    first = create_account(client, admin_token, "resume-first", worker["id"], "codex_subscription")
    second = create_account(client, admin_token, "resume-second", worker["id"], "codex_subscription")
    make_project(client, admin_token, "real-resume-project")
    project = client.get("/api/v0/projects/real-resume-project", headers=auth(admin_token)).json()
    project["allowed_paths"] = [str(tmp_path)]
    assert client.patch(
        "/api/v0/projects/real-resume-project", headers=auth(admin_token), json=project
    ).status_code == 200
    created = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "real-resume-project", "worker_id": worker["id"], "engine": "mock_echo_prompt",
        "provider": "test", "model": "mock", "auth_mode": "subscription", "workdir": str(tmp_path),
        "account_profile_id": first["id"],
    }).json()
    db_factory = get_session_factory()[1]
    db = db_factory()
    db_session = db.get(Session, created["id"])
    db_session.status = "failed"
    db_session.resume_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    db_session.engine_session_ref = "mock-ref"
    db.add(AgentEvent(session_id=created["id"], kind="message", source="native",
                      payload={"role": "user", "text": "предыдущий запрос"}))
    db.commit()
    db.close()
    switched = client.post(f"/api/v0/sessions/{created['id']}/continue-on-account", headers=auth(admin_token),
                           json={"account_profile_id": second["id"]})
    assert switched.status_code == 200, switched.text
    assert switched.json()["account_profile_id"] == second["id"]
    with live_server() as port:
        async def run_resumed():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                real_worker = AgentWorker(f"http://127.0.0.1:{port}", worker["id"], worker["worker_token"])
                assignments = (await http.get(f"/api/v0/{worker['id']}/assignments",
                                               headers=real_worker.headers)).json()
                assignment = next(item for item in assignments if item["id"] == created["id"])
                assert assignment["account_profile_id"] == second["id"]
                assert assignment["config_dir"] == second["config_dir"]
                assert assignment["engine_session_ref"] == "mock-ref"
                await real_worker.run_assignment(http, assignment)
        asyncio.run(run_resumed())
    resumed = client.get(f"/api/v0/sessions/{created['id']}", headers=auth(admin_token)).json()
    assert resumed["status"] == "completed" and resumed["account_profile_id"] == second["id"]
