"""Automatic limits refresh: one request per connected subscription account on an online worker, none twice."""
from datetime import datetime, timedelta, timezone

import pytest

from aihub_control.accounts.auto_limits import queue_limit_refreshes
from aihub_control.db import get_session_factory
from aihub_control.models import AccountProfile, Worker, WorkerRequest
from test_api_integration import admin_token, auth, clean_schema, client

pytestmark = pytest.mark.integration


def _account(db, account_id, worker_id, kind="claude_code_subscription", status="connected"):
    db.add(AccountProfile(id=account_id, name=account_id, kind=kind, worker_id=worker_id,
                          config_dir=f"~/.aihub/accounts/{account_id}/claude", models=[], status=status))


def test_queues_once_per_account_and_skips_offline(client, admin_token):  # noqa: F811
    for worker_id in ("on", "off"):
        client.post("/api/v0/workers", headers=auth(admin_token), json={"id": worker_id, "host": "h", "kind": "linux"})
    _, factory = get_session_factory()
    db = factory()
    db.get(Worker, "off").status = "offline"
    _account(db, "claude-on", "on")
    _account(db, "codex-on", "on", kind="codex_subscription")
    _account(db, "claude-pending", "on", status="pending_login")
    _account(db, "claude-off", "off")
    db.commit()

    assert queue_limit_refreshes(db) == 2
    queued = {r.response["account_id"] for r in db.query(WorkerRequest).filter_by(kind="limits_refresh")}
    assert queued == {"claude-on", "codex-on"}
    # Still in flight: nothing new on the next tick.
    assert queue_limit_refreshes(db) == 0
    # A request stuck for over ten minutes (the worker restarted) no longer blocks the account.
    for request in db.query(WorkerRequest).filter_by(kind="limits_refresh"):
        request.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    db.commit()
    assert queue_limit_refreshes(db) == 2
    # Answered requests older than a day are removed.
    for request in db.query(WorkerRequest).filter_by(kind="limits_refresh"):
        request.status, request.created_at = "completed", datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()
    queue_limit_refreshes(db)
    assert db.query(WorkerRequest).filter_by(kind="limits_refresh").count() == 2
    db.close()
