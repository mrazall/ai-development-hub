from datetime import datetime, timezone

# ruff: noqa: F811
import pytest

# Explicit imports only: `pytest_plugins` here made the DB autouse fixture global and skipped every unit test.
from test_api_integration import admin_token, auth, clean_schema, client

pytestmark = pytest.mark.integration


def test_backup_report_status_and_failure_notification(
    client, admin_token, clean_schema, monkeypatch
):
    monkeypatch.setenv("AIHUB_BACKUP_TOKEN", "backup-token-for-test")
    headers = {**auth("backup-token-for-test")}
    timestamp = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v0/backups/report",
        headers=headers,
        json={
            "id": "snap-ok",
            "repo": "restic-aihub",
            "kind": "database",
            "started_at": timestamp,
            "finished_at": timestamp,
            "ok": True,
            "size_bytes": 12,
            "tags": ["aihub"],
        },
    )
    assert response.status_code == 201
    assert client.get("/api/v0/backups", headers=auth(admin_token)).json()[0]["id"] == "snap-ok"
    status = client.get("/api/v0/backups/status", headers=auth(admin_token))
    assert status.status_code == 200
    assert status.json()[0]["kind"] == "database"
    assert status.json()[0]["rpo_exceeded"] is False

    failed = client.post(
        "/api/v0/backups/report",
        headers=headers,
        json={
            "id": "snap-failed",
            "repo": "restic-aihub",
            "kind": "database",
            "started_at": timestamp,
            "finished_at": timestamp,
            "ok": False,
            "error": "restic exited with status 1",
        },
    )
    assert failed.status_code == 201
    notifications = client.get("/api/v0/notifications", headers=auth(admin_token)).json()
    assert any(item["category"] == "backup.failed" for item in notifications)
