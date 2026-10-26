from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from ..approvals.service import decide, expire_pending
from ..auth import current_principal, db_dep, write_user
from ..deps import is_admin
from ..models import Approval, Project, ProjectMember, Session, User, WorkerToken
from ..schemas import ApprovalDecisionIn, ApprovalOut

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _visible_for_user(db, user: User, approval: Approval) -> bool:
    if is_admin(user):
        return True
    session = db.get(Session, approval.session_id)
    if not session:
        return False
    project = db.get(Project, session.project_id)
    member = db.get(ProjectMember, {"project_id": session.project_id, "user_id": user.id}) if project else None
    return bool(project and (project.visibility in {"shared", "public"} or member))


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    status: str = Query("pending", pattern=r"^(pending|approved|rejected|expired)$"),
    session_id: str | None = None,
    principal=Depends(current_principal),
    db=Depends(db_dep),
):
    expire_pending(db)
    query = select(Approval)
    if isinstance(principal, WorkerToken):
        query = query.where(Approval.worker_id == principal.worker_id)
    query = query.where(Approval.status == status)
    if session_id:
        query = query.where(Approval.session_id == session_id)
    approvals = list(db.scalars(query.order_by(Approval.requested_at)))
    if isinstance(principal, User):
        approvals = [item for item in approvals if _visible_for_user(db, principal, item)]
    db.commit()
    return approvals


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
def approval_decision(
    approval_id: str,
    data: ApprovalDecisionIn,
    user=Depends(write_user),
    db=Depends(db_dep),
):
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "approval not found")
    try:
        decide(db, approval, data.decision, user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    db.refresh(approval)
    return approval
