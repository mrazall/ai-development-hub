"""System health: the checks the page shows and the failure/recovery notifications."""
from datetime import datetime, timedelta, timezone

import pytest

from aihub_control.db import get_session_factory
from aihub_control.health import collect, notify_changes
from aihub_control.models import Notification, Worker
from test_api_integration import admin_token, auth, clean_schema, client

pytestmark = pytest.mark.integration


def _checks(report):
    return {item["key"]: item for item in report["checks"]}


def test_health_page_lists_every_check(client, admin_token):  # noqa: F811
    assert client.post("/api/v0/workers", headers=auth(admin_token),
                       json={"id": "w1", "host": "local", "kind": "linux"}).status_code == 200
    report = client.get("/api/v0/system/health", headers=auth(admin_token)).json()
    assert set(_checks(report)) == {"workers", "tailscale", "limits", "knowledge", "backups", "errors"}
    assert _checks(report)["tailscale"]["status"] == "unknown"  # no socket configured in tests
    assert report["status"] in {"ok", "unknown", "warning", "critical"}


def test_worker_going_offline_notifies_once_and_recovers(client, admin_token):  # noqa: F811
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "w1", "host": "local", "kind": "linux"})
    _, factory = get_session_factory()
    db = factory()
    try:
        worker = db.get(Worker, "w1")
        worker.status, worker.last_heartbeat_at = "online", datetime.now(timezone.utc)
        db.commit()
        notify_changes(db, collect(db))
        assert _checks(collect(db))["workers"]["status"] == "ok"

        worker.status, worker.last_heartbeat_at = "offline", datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert _checks(collect(db))["workers"]["status"] == "critical"
        notify_changes(db, collect(db))
        notify_changes(db, collect(db))  # still down: no second notification
        titles = [row.title for row in db.query(Notification).filter_by(category="system.health")
                  .filter(Notification.body.like("[workers]%"))]
        users = {row.user_id for row in db.query(Notification).filter_by(category="system.health")}
        assert titles.count("Сбой: Воркеры") == len(users)

        worker.status, worker.last_heartbeat_at = "online", datetime.now(timezone.utc)
        db.commit()
        notify_changes(db, collect(db))
        latest = db.query(Notification).filter(Notification.body.like("[workers]%")).order_by(
            Notification.created_at.desc()).first()
        assert latest.title == "Восстановлено: Воркеры"
    finally:
        db.close()
