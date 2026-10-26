import pytest

from aihub_control.db import get_session_factory
from aihub_control.models import AgentEvent, Session
from test_api_integration import admin_token, auth, clean_schema, client


pytestmark = pytest.mark.integration


def _worker(client, token):  # noqa: F811
    response = client.post(
        "/api/v0/workers", headers=auth(token),
        json={"id": "chat-worker", "host": "local", "kind": "linux"},
    )
    assert response.status_code == 200
    # Chats need a Claude subscription profile: without one Claude would run with an unlogged default home.
    profile = client.post(
        "/api/v0/accounts", headers=auth(token),
        json={"id": "claude-chat", "name": "Claude", "kind": "claude_code_subscription", "worker_id": "chat-worker"},
    )
    assert profile.status_code == 201


def test_chat_lifecycle_and_chain_history(client, admin_token):  # noqa: F811
    _worker(client, admin_token)
    created = client.post(
        "/api/v0/chats", headers=auth(admin_token),
        json={"text": "  Что у меня на\nVDS? ", "model": "sonnet"},
    )
    assert created.status_code == 201, created.text
    chat = created.json()
    assert chat["title"] == "Что у меня на VDS?"
    assert chat["account_profile_id"] == "claude-chat"

    _, factory = get_session_factory()
    db = factory()
    root = db.get(Session, chat["id"])
    root.status = "completed"
    root.engine_session_ref = "claude-1"
    child_id = root.id
    db.add(AgentEvent(session_id=child_id, kind="message", source="native", payload={"role": "assistant", "text": "Первый ответ"}))
    db.commit()
    db.close()

    continued = client.post(
        f"/api/v0/sessions/{child_id}/continue", headers=auth(admin_token),
        json={"text": "Продолжение", "model": "opus"},
    )
    assert continued.status_code == 201
    child_id = continued.json()["id"]
    db = factory()
    db.add_all([
        AgentEvent(session_id=child_id, kind="message", source="native", payload={"role": "assistant", "text": "Второй ответ"}),
        AgentEvent(session_id=child_id, kind="message", source="native", payload={"role": "assistant", "text": "скрытый", "partial": True}),
        AgentEvent(session_id=child_id, kind="tool.call", source="native", payload={"name": "knowledge", "text": "x" * 200}),
    ])
    db.commit()
    db.close()

    details = client.get(f"/api/v0/chats/{chat['id']}", headers=auth(admin_token))
    assert details.status_code == 200
    messages = details.json()["messages"]
    assert [message["text"] for message in messages if message["role"] != "tool"] == [
        "  Что у меня на\nVDS? ", "Первый ответ", "Продолжение", "Второй ответ"
    ]
    assert messages[-1]["role"] == "tool"
    assert len(messages[-1]["tool_summary"]) == 160
    assert client.get("/api/v0/chats?q=VDS", headers=auth(admin_token)).json()[0]["id"] == chat["id"]

    assert client.patch(
        f"/api/v0/chats/{chat['id']}", headers=auth(admin_token), json={"pinned": True}
    ).json()["pinned"] is True
    assert client.delete(f"/api/v0/chats/{chat['id']}", headers=auth(admin_token)).status_code == 200
    assert client.get(f"/api/v0/chats/{chat['id']}", headers=auth(admin_token)).status_code == 404


def test_chat_requires_online_worker(client, admin_token):  # noqa: F811
    response = client.post("/api/v0/chats", headers=auth(admin_token), json={"text": "hello"})
    assert response.status_code == 409
    assert "worker" in response.json()["detail"]


def test_chat_effort_is_kept_and_can_change_on_continue(client, admin_token):  # noqa: F811
    _worker(client, admin_token)
    created = client.post("/api/v0/chats", headers=auth(admin_token), json={"text": "Привет", "effort": "high"})
    assert created.status_code == 201, created.text
    assert created.json()["effort"] == "high"
    assert client.post("/api/v0/chats", headers=auth(admin_token), json={"text": "x", "effort": "huge"}).status_code == 422
    _, factory = get_session_factory()
    db = factory()
    root = db.get(Session, created.json()["id"])
    root.status, root.engine_session_ref = "completed", "claude-1"
    db.commit()
    db.close()
    continued = client.post(f"/api/v0/sessions/{created.json()['id']}/continue", headers=auth(admin_token),
                            json={"text": "Дальше", "effort": "max"})
    assert continued.status_code == 201, continued.text
    chat = client.get(f"/api/v0/chats/{created.json()['id']}", headers=auth(admin_token)).json()
    assert chat["effort"] == "max"
