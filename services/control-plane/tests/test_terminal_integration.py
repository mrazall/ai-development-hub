"""Embedded terminal relay: browser frames reach the worker channel and back, admins only."""
import pytest
from starlette.websockets import WebSocketDisconnect

from test_api_integration import admin_token, auth, client, clean_schema, make_project, make_session

pytestmark = pytest.mark.integration


def _ticket(http, token):
    return http.post("/api/v0/events/stream-ticket", headers=auth(token)).json()["ticket"]


def test_terminal_relays_between_browser_and_worker(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "worker-a", "host": "local", "kind": "linux"}).json()
    session = make_session(client, admin_token, worker_id="worker-a")

    with client.websocket_connect("/api/v0/workers/worker-a/terminal-channel",
                                  headers=auth(worker["worker_token"])) as channel:
        with client.websocket_connect(f"/api/v0/terminal/{session['id']}/ws") as browser:
            browser.send_json({"t": "auth", "ticket": _ticket(client, admin_token)})
            opened = channel.receive_json()
            assert opened["t"] == "open" and opened["session_id"] == session["id"]
            tid = opened["tid"]
            channel.send_json({"t": "ready", "tid": tid})
            assert browser.receive_json() == {"t": "ready"}
            browser.send_json({"t": "i", "d": "ls\n"})
            assert channel.receive_json() == {"t": "i", "tid": tid, "d": "ls\n"}
            browser.send_json({"t": "z", "c": 120, "r": 40})
            assert channel.receive_json() == {"t": "z", "tid": tid, "c": 120, "r": 40}
            channel.send_json({"t": "o", "tid": tid, "d": "file.txt\r\n"})
            assert browser.receive_json() == {"t": "o", "d": "file.txt\r\n"}
        assert channel.receive_json() == {"t": "close", "tid": tid}


def test_terminal_requires_valid_ticket_and_worker_token(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "worker-a", "host": "local", "kind": "linux"})
    session = make_session(client, admin_token, worker_id="worker-a")
    with client.websocket_connect(f"/api/v0/terminal/{session['id']}/ws") as browser:
        browser.send_json({"t": "auth", "ticket": "forged"})
        assert browser.receive_json() == {"t": "x", "reason": "unauthorized"}
    with client.websocket_connect(f"/api/v0/terminal/{session['id']}/ws") as browser:
        browser.send_json({"t": "auth", "ticket": _ticket(client, admin_token)})
        assert browser.receive_json() == {"t": "x", "reason": "worker_offline"}
    # A bad worker token is refused before the WebSocket is accepted.
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/api/v0/workers/worker-a/terminal-channel", headers=auth("bogus")
    ) as channel:
        channel.receive_json()
