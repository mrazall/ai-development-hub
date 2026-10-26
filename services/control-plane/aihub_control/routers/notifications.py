from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from ..auth import current_user, db_dep
from ..models import Notification, Project, ProjectMember, Session

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _visible(user):
    """Notifications the user may see: their own, and shared ones of projects they can access."""
    accessible = select(Project.id).where(
        (Project.visibility.in_(["shared", "public"]))
        | Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
    )
    return (
        select(Notification)
        .outerjoin(Session, Notification.session_id == Session.id)
        .outerjoin(Project, Session.project_id == Project.id)
        .where(
            or_(
                Notification.user_id == user.id,
                (
                    Notification.user_id.is_(None)
                    & (Notification.session_id.is_(None) | Project.id.in_(accessible))
                ),
            )
        )
    )


@router.get("")
def list_notifications(
    unread: bool = False,
    limit: int = Query(100, ge=1, le=500),
    user=Depends(current_user),
    db=Depends(db_dep),
):
    # Unread first: an old unread item must not hide below the limit while the bell still counts it.
    query = _visible(user).order_by(Notification.read_at.is_not(None), Notification.created_at.desc()).limit(limit)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    return list(db.scalars(query))


@router.post("/read-all")
def mark_all_read(user=Depends(current_user), db=Depends(db_dep)):
    now = datetime.now(timezone.utc)
    items = list(db.scalars(_visible(user).where(Notification.read_at.is_(None))))
    for notification in items:
        notification.read_at = now
    db.commit()
    return {"ok": True, "read": len(items)}


@router.post("/{notification_id}/read")
def mark_read(notification_id: str, user=Depends(current_user), db=Depends(db_dep)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id not in (None, user.id):
        return {"ok": True}
    if notification.user_id is None and notification.session_id:
        session = db.get(Session, notification.session_id)
        if not session:
            return {"ok": True}
        project = db.get(Project, session.project_id)
        member = db.get(ProjectMember, {"project_id": session.project_id, "user_id": user.id})
        if not project or (project.visibility == "private" and not member):
            return {"ok": True}
    notification.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
