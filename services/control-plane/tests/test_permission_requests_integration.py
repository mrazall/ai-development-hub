"""Claude Code in "ask" mode: a permission request becomes an approval in the panel, the owner decides, the agent
gets the answer. Found in production: a workspace session could edit files but every command was silently denied."""
import pytest

from test_api_integration import admin_token, auth, clean_schema, client, make_project

pytestmark = pytest.mark.integration


def _ask_session(client, admin_token, mode="ask"):  # noqa: F811
    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "worker-a", "host": "local", "kind": "linux"}).json()
    session = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "demo", "worker_id": "worker-a", "engine": "claude_code", "provider": "anthropic",
        "model": "claude-opus-5-5", "auth_mode": "subscription", "workdir": "/tmp/project", "permission_mode": mode,
    }).json()
    # As the worker does: claiming the assignment returns it with the scoped hub token.
    assignment = client.post(f"/api/v0/assignments/{session['id']}/claim", headers=auth(worker["worker_token"]))
    assert assignment.status_code == 200, assignment.text
    return session, assignment.json()


def test_ask_session_gets_a_permission_token_and_the_owner_decides(client, admin_token):  # noqa: F811
    session, assignment = _ask_session(client, admin_token)
    assert assignment["permission_mode"] == "ask" and assignment.get("hub_token")
    agent = auth(assignment["hub_token"])

    asked = client.post(f"/api/v0/sessions/{session['id']}/permission-requests", headers=agent,
                        json={"tool_name": "Bash", "input": {"command": "pnpm test"}})
    assert asked.status_code == 201 and asked.json()["status"] == "pending"
    approval_id = asked.json()["id"]
    assert client.get(f"/api/v0/sessions/{session['id']}", headers=auth(admin_token)).json()["status"] == "waiting_approval"
    feed = client.get(f"/api/v0/events?session_id={session['id']}&limit=50&newest=true",
                      headers=auth(admin_token)).json()
    feed = feed.get("items", feed) if isinstance(feed, dict) else feed
    card = [event for event in feed if event["kind"] == "approval.request"]
    assert card and card[-1]["payload"]["approval_id"] == approval_id and "pnpm test" in card[-1]["payload"]["summary"]

    decided = client.post(f"/api/v0/approvals/{approval_id}/decision", headers=auth(admin_token),
                          json={"decision": "approved"})
    assert decided.status_code == 200
    status = client.get(f"/api/v0/sessions/{session['id']}/permission-requests/{approval_id}", headers=agent)
    assert status.json()["status"] == "approved"


def test_permission_endpoints_need_this_sessions_scope(client, admin_token):  # noqa: F811
    session, _ = _ask_session(client, admin_token, mode="edits")
    # An "edits" session has no hub token at all; a user token is not a permission token either.
    refused = client.post(f"/api/v0/sessions/{session['id']}/permission-requests", headers=auth(admin_token),
                          json={"tool_name": "Bash", "input": {}})
    assert refused.status_code == 403


def test_continuation_keeps_or_changes_the_permission_mode(client, admin_token):  # noqa: F811
    from aihub_control.db import get_session_factory
    from aihub_control.models import Session

    session, _ = _ask_session(client, admin_token, mode="edits")
    _, factory = get_session_factory()
    with factory() as db:  # the agent finished: a conversation to continue
        row = db.get(Session, session["id"])
        row.status, row.engine_session_ref = "completed", "conv-1"
        db.commit()
    kept = client.post(f"/api/v0/sessions/{session['id']}/continue", headers=auth(admin_token),
                       json={"text": "try again"}).json()
    assert kept["permission_mode"] == "edits"
    with factory() as db:
        db.get(Session, kept["id"]).status = "completed"
        db.commit()
    # "Try again, and now you may ask": the continuation switches to ask and gets the hub permission tool.
    asked = client.post(f"/api/v0/sessions/{kept['id']}/continue", headers=auth(admin_token),
                        json={"text": "try again", "permission_mode": "ask"}).json()
    assert asked["permission_mode"] == "ask"
    with factory() as db:
        config = db.get(Session, asked["id"]).mcp_config or {}
    assert config.get("user_id") and "knowledge" in config.get("mcpServers", {})


def test_feed_of_a_continuation_chain(client, admin_token):  # noqa: F811
    # The workspace shows a session and its continuations as one conversation: /events?session_ids=a,b.
    session, _ = _ask_session(client, admin_token, mode="edits")
    other = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "project_id": "demo", "worker_id": "worker-a", "engine": "mock", "provider": "test", "model": "mock",
        "auth_mode": "local", "workdir": "/tmp/project", "parent_session_id": session["id"],
    }).json()
    for sid, text in ((session["id"], "first"), (other["id"], "second")):
        client.post(f"/api/v0/sessions/{sid}/events", headers=auth(admin_token),
                    json=[{"kind": "message", "payload": {"role": "user", "text": text}}])
    feed = client.get(f"/api/v0/events?session_ids={session['id']},{other['id']}&limit=50&newest=true",
                      headers=auth(admin_token)).json()
    texts = [event["payload"].get("text") for event in feed if event["kind"] == "message"]
    assert texts == ["first", "second"]


def test_task_follows_its_session(client, admin_token):  # noqa: F811
    # Found live: every task stayed «draft» although its sessions had run and finished.
    make_project(client, admin_token)
    task = client.post("/api/v0/projects/demo/tasks", headers=auth(admin_token),
                       json={"title": "Почини звонок", "body": "x", "idempotency_key": "k-1"}).json()
    session = client.post("/api/v0/sessions", headers=auth(admin_token), json={
        "task_id": task["id"], "project_id": "demo", "worker_id": "worker-a", "engine": "mock", "provider": "test",
        "model": "mock", "auth_mode": "local", "workdir": "/tmp/project",
    }).json()

    def status(value):
        client.post(f"/api/v0/sessions/{session['id']}/events", headers=auth(admin_token),
                    json=[{"kind": "session.status", "payload": {"status": value}}])
        return client.get(f"/api/v0/projects/demo/tasks/{task['id']}", headers=auth(admin_token)).json()["status"]

    assert status("starting") == "in_progress"
    assert status("running") == "in_progress"
    assert status("completed") == "review"
    client.patch(f"/api/v0/projects/demo/tasks/{task['id']}", headers=auth(admin_token),
                 json={"title": "Почини звонок", "body": "x", "status": "done"})
    assert status("running") == "done"  # the owner's decision stays
