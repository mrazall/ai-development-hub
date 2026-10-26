"""Approval persistence and worker-facing helpers."""

from sqlalchemy import select

from ..models import Approval


def pending_decisions_for(db, worker_id: str) -> list[Approval]:
    """Return pending approvals for a worker, for long-poll integration."""
    return list(
        db.scalars(
            select(Approval)
            .where(Approval.worker_id == worker_id, Approval.status == "pending")
            .order_by(Approval.requested_at)
        )
    )
