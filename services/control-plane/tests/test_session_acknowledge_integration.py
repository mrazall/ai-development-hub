import pytest

from test_api_integration import admin_token as ack_admin
from test_api_integration import auth, make_project, make_session
from test_api_integration import clean_schema as clean_schema_fixture
from test_api_integration import client as ack_client

from aihub_control.db import get_session_factory
from aihub_control.models import Session

pytestmark = pytest.mark.integration


def _set_status(session_id: str, status: str) -> None:
    _, factory = get_session_factory()
    with factory() as db:
        db.get(Session, session_id).status = status
        db.commit()


def test_a_failed_session_can_be_marked_fine_until_it_runs_again(ack_client, ack_admin):  # noqa: F811
    headers = auth(ack_admin)
    make_project(ack_client, ack_admin)
    session = make_session(ack_client, ack_admin)
    assert ack_client.post(f"/api/v0/sessions/{session['id']}/acknowledge", headers=headers).status_code == 409

    _set_status(session["id"], "failed")
    marked = ack_client.post(f"/api/v0/sessions/{session['id']}/acknowledge", headers=headers)
    assert marked.status_code == 200 and marked.json()["acknowledged_at"]
    assert marked.json()["status"] == "failed"

    _set_status(session["id"], "running")  # resumed: a new failure must show again
    _set_status(session["id"], "failed")
    assert ack_client.get(f"/api/v0/sessions/{session['id']}", headers=headers).json()["acknowledged_at"] is None

    ack_client.post(f"/api/v0/sessions/{session['id']}/acknowledge", headers=headers)
    undone = ack_client.delete(f"/api/v0/sessions/{session['id']}/acknowledge", headers=headers)
    assert undone.json()["acknowledged_at"] is None
