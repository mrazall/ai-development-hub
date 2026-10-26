import os

import httpx2 as httpx

from aihub_control.auth import hash_password
from aihub_control.db import get_session_factory
from aihub_control.models import User
from aihub_control.routers import accounts as accounts_router
from test_api_integration import admin_token as account_admin
from test_api_integration import auth
from test_api_integration import clean_schema as clean_schema_fixture
from test_api_integration import client as account_client
from test_api_integration import make_project, make_session

import pytest

pytestmark = pytest.mark.integration


def test_account_crud_secret_redaction_and_disable(account_client, account_admin, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AIHUB_ACCOUNTS_SECRET_DIR", str(tmp_path))
    headers = auth(account_admin)
    created = account_client.post(
        "/api/v0/accounts",
        headers=headers,
        json={"id": "claude-one", "name": "Claude one", "kind": "claude_code_subscription", "worker_id": "w1"},
    )
    assert created.status_code == 201
    assert created.json()["config_dir"] == "~/.aihub/accounts/claude-one/claude"
    assert account_client.post("/api/v0/accounts/claude-one/secret", headers=headers, json={"secret": "never-return-this"}).status_code == 409
    assert account_client.post("/api/v0/accounts/claude-one/disable", headers=headers).status_code == 200
    assert account_client.delete("/api/v0/accounts/claude-one", headers=headers).status_code == 204

    account_client.post(
        "/api/v0/accounts",
        headers=headers,
        json={"id": "openai-one", "name": "OpenAI", "kind": "openai_api", "worker_id": "w1", "base_url": "https://provider.test"},
    ).json()
    response = account_client.post("/api/v0/accounts/openai-one/secret", headers=headers, json={"secret": "never-return-this"})
    assert response.status_code == 200
    assert "never-return-this" not in response.text
    assert response.json()["secret_fingerprint"]
    assert os.stat(tmp_path / "openai-one.key").st_mode & 0o777 == 0o600


def test_provider_check_uses_models_endpoint_without_exposing_secret(account_client, account_admin, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AIHUB_ACCOUNTS_SECRET_DIR", str(tmp_path))
    headers = auth(account_admin)
    account_client.post("/api/v0/accounts", headers=headers, json={"id": "ollama-one", "name": "Ollama", "kind": "ollama", "worker_id": "w1", "base_url": "http://ollama.test"})
    account_client.post("/api/v0/accounts/ollama-one/secret", headers=headers, json={"secret": "local-secret"})

    def handler(request):
        assert request.url.path == "/api/tags"
        assert "local-secret" not in str(request.headers)
        return httpx.Response(200, json={"models": [{"name": "llama3"}]})

    real_client = httpx.Client
    monkeypatch.setattr(accounts_router.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    response = account_client.post("/api/v0/accounts/ollama-one/check", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert response.json()["models"] == ["llama3"]


def test_gemini_key_goes_in_header_not_url(account_client, account_admin, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AIHUB_ACCOUNTS_SECRET_DIR", str(tmp_path))
    headers = auth(account_admin)
    account_client.post("/api/v0/accounts", headers=headers, json={"id": "gem", "name": "Gemini", "kind": "gemini_api", "worker_id": "w1"})
    assert account_client.post("/api/v0/accounts/gem/secret", headers=headers, json={"secret": "g-secret-123"}).status_code == 200

    def handler(request):
        assert "g-secret-123" not in str(request.url)  # URLs end up in client/proxy logs
        assert request.headers.get("x-goog-api-key") == "g-secret-123"
        return httpx.Response(200, json={"models": [{"name": "models/gemini-x"}]})

    real_client = httpx.Client
    monkeypatch.setattr(accounts_router.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    assert account_client.post("/api/v0/accounts/gem/check", headers=headers).json()["status"] == "connected"


def test_ollama_check_needs_no_secret(account_client, account_admin, monkeypatch):  # noqa: F811
    headers = auth(account_admin)
    account_client.post("/api/v0/accounts", headers=headers, json={"id": "olla", "name": "Ollama", "kind": "ollama", "worker_id": "w1", "base_url": "http://ollama.test"})
    real_client = httpx.Client
    handler = lambda request: httpx.Response(200, json={"models": [{"name": "qwen3"}]})
    monkeypatch.setattr(accounts_router.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    assert account_client.post("/api/v0/accounts/olla/check", headers=headers).json()["status"] == "connected"


def test_worker_approval_request_is_pending_and_admin_decision_is_audited(
    account_client,  # noqa: F811
    account_admin,  # noqa: F811
    clean_schema_fixture,  # noqa: F811
):
    make_project(account_client, account_admin, "approval-project", visibility="shared")
    worker = account_client.post(
        "/api/v0/workers",
        headers=auth(account_admin),
        json={"id": "approval-worker", "host": "local", "kind": "linux"},
    ).json()
    session = make_session(account_client, account_admin, "approval-project", "approval-worker")
    response = account_client.post(
        f"/api/v0/sessions/{session['id']}/events",
        headers=auth(worker["worker_token"]),
        json=[
            {
                "kind": "approval.request",
                "payload": {
                    "action": "git push",
                    "summary": "Отправить изменения в удалённый репозиторий",
                    "risk": "high",
                },
            }
        ],
    )
    assert response.status_code == 200
    pending = account_client.get("/api/v0/approvals?status=pending", headers=auth(account_admin))
    approval = pending.json()[0]
    assert approval["action"] == "git push"
    assert account_client.get(
        f"/api/v0/approvals?session_id={session['id']}",
        headers=auth(worker["worker_token"]),
    ).json()[0]["id"] == approval["id"]
    decision = account_client.post(
        f"/api/v0/approvals/{approval['id']}/decision",
        headers=auth(account_admin),
        json={"decision": "approved"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    events = account_client.get(
        f"/api/v0/events?session_id={session['id']}", headers=auth(account_admin)
    ).json()
    assert any(event["kind"] == "approval.decision" for event in events)


def test_viewer_cannot_decide_approval(
    account_client,  # noqa: F811
    account_admin,  # noqa: F811
    clean_schema_fixture,  # noqa: F811
):
    make_project(account_client, account_admin, "approval-viewer", visibility="shared")
    worker = account_client.post(
        "/api/v0/workers",
        headers=auth(account_admin),
        json={"id": "approval-viewer-worker", "host": "local", "kind": "linux"},
    ).json()
    session = make_session(account_client, account_admin, "approval-viewer", "approval-viewer-worker")
    account_client.post(
        f"/api/v0/sessions/{session['id']}/events",
        headers=auth(worker["worker_token"]),
        json=[{"kind": "approval.request", "payload": {"action": "deploy", "summary": "deploy", "risk": "critical"}}],
    )
    approval = account_client.get("/api/v0/approvals", headers=auth(account_admin)).json()[0]
    _, factory = get_session_factory()
    db = factory()
    db.add(User(username="approval-viewer", password_hash=hash_password("viewer-password"), role="viewer"))
    db.commit()
    db.close()
    viewer_login = account_client.post(
        "/api/v0/auth/login",
        json={"username": "approval-viewer", "password": "viewer-password"},
    )
    response = account_client.post(
        f"/api/v0/approvals/{approval['id']}/decision",
        headers=auth(viewer_login.json()["access_token"]),
        json={"decision": "rejected"},
    )
    assert response.status_code == 403


def test_worker_account_error_creates_auth_notification(
    account_client,  # noqa: F811
    account_admin,  # noqa: F811
    clean_schema_fixture,  # noqa: F811
):
    worker = account_client.post(
        "/api/v0/workers",
        headers=auth(account_admin),
        json={"id": "account-worker", "host": "local", "kind": "linux"},
    ).json()
    account = account_client.post(
        "/api/v0/accounts",
        headers=auth(account_admin),
        json={
            "id": "subscription-account",
            "name": "Subscription",
            "kind": "claude_code_subscription",
            "worker_id": "account-worker",
        },
    ).json()
    status = account_client.post(
        f"/api/v0/accounts/{account['id']}/status",
        headers=auth(worker["worker_token"]),
        json={"status": "error", "detail": "login expired"},
    )
    assert status.status_code == 200
    notifications = account_client.get(
        "/api/v0/notifications", headers=auth(account_admin)
    ).json()
    assert any(item["category"] == "account.auth_failed" for item in notifications)
    marked = account_client.post("/api/v0/notifications/read-all", headers=auth(account_admin))
    assert marked.status_code == 200 and marked.json()["read"] >= 1
    unread = account_client.get("/api/v0/notifications?unread=true", headers=auth(account_admin)).json()
    assert unread == []
