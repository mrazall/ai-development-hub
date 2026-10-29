import io

import pytest

from test_api_integration import admin_token, auth, client, clean_schema, make_project, make_session

pytestmark = pytest.mark.integration


def test_upload_list_download_and_delete_attachment(client, admin_token, clean_schema):  # noqa: F811
    make_project(client, admin_token)
    session = make_session(client, admin_token)
    response = client.post(
        f"/api/v0/sessions/{session['id']}/attachments",
        headers=auth(admin_token),
        files={"file": ("pixel.png", io.BytesIO(b"\x89PNG\r\n\x1a\ncontent"), "image/png")},
    )
    assert response.status_code == 201
    attachment = response.json()
    assert client.get(f"/api/v0/sessions/{session['id']}/attachments", headers=auth(admin_token)).json()[0]["id"] == attachment["id"]
    downloaded = client.get(f"/api/v0/attachments/{attachment['id']}", headers=auth(admin_token))
    assert downloaded.status_code == 200 and downloaded.content.startswith(b"\x89PNG")
    assert client.delete(f"/api/v0/attachments/{attachment['id']}", headers=auth(admin_token)).status_code == 204


def test_worker_attachment_api_scopes_session_and_returns_metadata(client, admin_token, clean_schema):  # noqa: F811
    make_project(client, admin_token)
    session = make_session(client, admin_token, worker_id="worker-a")
    upload = client.post(
        f"/api/v0/sessions/{session['id']}/attachments",
        headers=auth(admin_token),
        files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert upload.status_code == 201
    worker = client.post(
        "/api/v0/workers",
        headers=auth(admin_token),
        json={"id": "worker-a", "host": "local", "kind": "linux"},
    ).json()
    worker_headers = auth(worker["worker_token"])
    metadata = client.get(
        f"/api/v0/assignments/{session['id']}/attachments", headers=worker_headers
    )
    assert metadata.status_code == 200
    assert metadata.json()[0] == {
        "id": upload.json()["id"],
        "original_name": "report.txt",
        "mime_type": "text/plain",
        "size_bytes": 5,
    }
    downloaded = client.get(
        f"/api/v0/assignments/{session['id']}/attachments/{upload.json()['id']}",
        headers=worker_headers,
    )
    assert downloaded.status_code == 200 and downloaded.content == b"hello"
    foreign = make_session(client, admin_token, worker_id="worker-b")
    assert client.get(
        f"/api/v0/assignments/{foreign['id']}/attachments", headers=worker_headers
    ).status_code == 404


def test_project_delete_is_soft_and_active_sessions_block_it(client, admin_token, clean_schema):  # noqa: F811
    make_project(client, admin_token)
    make_session(client, admin_token)
    blocked = client.delete("/api/v0/projects/demo", headers=auth(admin_token))
    assert blocked.status_code == 409
    # Stop the session via the API, then verify the reversible soft delete.
    session = client.get("/api/v0/sessions?project_id=demo", headers=auth(admin_token)).json()[0]
    assert client.post(f"/api/v0/sessions/{session['id']}/stop", headers=auth(admin_token)).status_code == 200
    assert client.delete("/api/v0/projects/demo", headers=auth(admin_token)).status_code == 204
    assert client.get("/api/v0/projects/demo", headers=auth(admin_token)).status_code == 200
    assert client.post("/api/v0/projects/demo/restore", headers=auth(admin_token)).status_code == 200


def test_screenshot_sent_with_a_continuation_reaches_the_worker(client, admin_token, clean_schema):  # noqa: F811
    # Found live: «Скриншот до меня не дошёл». The composer uploads to the finished session on screen; the
    # continuation is a new session, and the worker lists only that session's attachments.
    from aihub_control.db import get_session_factory
    from aihub_control.models import Session

    make_project(client, admin_token)
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "worker-a", "host": "local", "kind": "linux"}).json()
    session = make_session(client, admin_token)
    _, factory = get_session_factory()
    with factory() as db:
        row = db.get(Session, session["id"])
        row.status, row.engine_session_ref = "completed", "conv-1"
        db.commit()
    shot = client.post(f"/api/v0/sessions/{session['id']}/attachments", headers=auth(admin_token),
                       files={"file": ("screen.png", io.BytesIO(b"\x89PNG\r\n\x1a\nshot"), "image/png")}).json()
    child = client.post(f"/api/v0/sessions/{session['id']}/continue", headers=auth(admin_token),
                        json={"text": "see the screenshot", "attachment_ids": [shot["id"]]}).json()
    listed = client.get(f"/api/v0/assignments/{child['id']}/attachments", headers=auth(worker["worker_token"])).json()
    assert [item["id"] for item in listed] == [shot["id"]]
    content = client.get(f"/api/v0/assignments/{child['id']}/attachments/{shot['id']}",
                         headers=auth(worker["worker_token"]))
    assert content.status_code == 200 and content.content.endswith(b"shot")
