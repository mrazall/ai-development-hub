from datetime import datetime, timedelta, timezone

from test_api_integration import admin_token, auth, client, clean_schema, make_project
from aihub_control.db import get_session_factory
from aihub_control.models import Project
from aihub_control.orchestration.lifecycle import purge_expired

import pytest

pytestmark = pytest.mark.integration


def test_purge_removes_hub_records_but_not_workdir(client, admin_token, clean_schema, tmp_path):  # noqa: F811
    make_project(client, admin_token)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    marker = workdir / "keep.txt"
    marker.write_text("do not remove", encoding="utf-8")
    response = client.post(
        "/api/v0/sessions",
        headers=auth(admin_token),
        json={
            "project_id": "demo", "worker_id": "worker-a", "engine": "mock",
            "provider": "test", "model": "test", "auth_mode": "none",
            "workdir": str(workdir),
        },
    )
    assert response.status_code == 200
    session = response.json()
    assert client.post(f"/api/v0/sessions/{session['id']}/stop", headers=auth(admin_token)).status_code == 200
    assert client.delete("/api/v0/projects/demo", headers=auth(admin_token)).status_code == 204
    _, factory = get_session_factory()
    db = factory()
    project = db.get(Project, "demo")
    project.deleted_at = datetime.now(timezone.utc) - timedelta(days=15)
    db.commit()
    result = purge_expired(db)
    db.close()
    assert result["projects"] == 1
    assert not client.get("/api/v0/projects/demo", headers=auth(admin_token)).json().get("id")
    assert marker.read_text(encoding="utf-8") == "do not remove"



def test_agent_events_stay_append_only_outside_purge(client, admin_token, clean_schema):  # noqa: F811
    from sqlalchemy import text
    from test_api_integration import make_session

    make_project(client, admin_token, "append-only")
    session = make_session(client, admin_token, "append-only")
    posted = client.post(
        f"/api/v0/sessions/{session['id']}/events", headers=auth(admin_token), json=[{"kind": "output", "payload": {}}]
    )
    assert posted.status_code < 300
    engine, _ = get_session_factory()
    for statement in ("UPDATE control.agent_events SET kind = kind", "DELETE FROM control.agent_events"):
        with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
            conn.execute(text(statement))
    # Even inside a purge transaction UPDATE stays forbidden; only DELETE is let through.
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("SET LOCAL aihub.purge = 'on'"))
        conn.execute(text("UPDATE control.agent_events SET kind = kind"))
