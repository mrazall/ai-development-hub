from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import AgentEvent, Approval, Session
from ..orchestration.notifications import notify_users

DEFAULT_APPROVAL_TTL = timedelta(hours=24)


def expire_approval(approval: Approval, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if approval.status == "pending" and approval.expires_at and approval.expires_at <= now:
        approval.status = "expired"
        return True
    return False


def expire_pending(db) -> None:
    now = datetime.now(timezone.utc)
    for approval in db.scalars(select(Approval).where(Approval.status == "pending")):
        expire_approval(approval, now)


def create_from_event(db, session: Session, payload: dict) -> Approval | None:
    action = payload.get("action")
    summary = payload.get("summary")
    risk = payload.get("risk")
    if not all(isinstance(value, str) and value.strip() for value in (action, summary, risk)):
        return None
    approval = Approval(
        session_id=session.id,
        worker_id=session.worker_id,
        action=action[:255],
        summary=summary,
        risk=risk[:32],
        expires_at=datetime.now(timezone.utc) + DEFAULT_APPROVAL_TTL,
    )
    db.add(approval)
    session.status = "waiting_approval"
    notify_users(
        db,
        "approval.required",
        "Требуется подтверждение действия",
        body=f"{action[:255]}: {summary}",
        severity="warning",
        session_id=session.id,
    )
    return approval


def decide(db, approval: Approval, decision: str, user_id: str) -> Approval:
    now = datetime.now(timezone.utc)
    if expire_approval(approval, now):
        db.commit()
    if approval.status != "pending":
        raise ValueError("approval is no longer pending")
    approval.status = decision
    approval.decided_at = now
    approval.decided_by = user_id
    db.add(
        AgentEvent(
            session_id=approval.session_id,
            kind="approval.decision",
            source="native",
            payload={"approval_id": approval.id, "decision": decision},
        )
    )
    session = db.get(Session, approval.session_id)
    if session and session.status == "waiting_approval":
        session.status = "running" if decision == "approved" else "blocked"
    return approval
