"""Automatic limits refresh: the worker reads the CLI's own /usage or /status, so checking costs no limit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from ..models import AccountProfile, Worker, WorkerRequest
from .service import SUBSCRIPTION_KINDS

KIND = "limits_refresh"
# A request older than this no longer blocks the next one (the worker restarted in the middle of it).
STUCK_AFTER = timedelta(minutes=10)
KEEP_DONE = timedelta(days=1)


def queue_limit_refreshes(db, now: datetime | None = None) -> int:
    """Queue one refresh per connected subscription account on an online worker, unless one is in flight."""
    now = now or datetime.now(timezone.utc)
    db.execute(delete(WorkerRequest).where(
        WorkerRequest.kind == KIND, WorkerRequest.status.in_(["completed", "failed"]),
        WorkerRequest.created_at < now - KEEP_DONE))
    online = set(db.scalars(select(Worker.id).where(Worker.status == "online")))
    in_flight = {
        (request.response or {}).get("account_id")
        for request in db.scalars(select(WorkerRequest).where(
            WorkerRequest.kind == KIND, WorkerRequest.status.in_(["queued", "running"]),
            WorkerRequest.created_at >= now - STUCK_AFTER))
    }
    queued = 0
    for account in db.scalars(select(AccountProfile).where(AccountProfile.kind.in_(SUBSCRIPTION_KINDS))):
        if account.worker_id not in online or account.id in in_flight or account.status != "connected":
            continue
        db.add(WorkerRequest(worker_id=account.worker_id, kind=KIND,
                             response={"account_id": account.id, "kind": account.kind, "auto": True}))
        queued += 1
    db.commit()
    return queued
