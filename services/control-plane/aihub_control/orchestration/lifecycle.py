"""Retention and final project cleanup for control-plane records only."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select, text

from ..config import Settings
from ..models import (
    AgentEvent,
    Attachment,
    Project,
    ProjectLifecycleError,
    ProjectMember,
    Session,
    Task,
)


def purge_expired(db, now: datetime | None = None) -> dict[str, int]:
    """Purge expired hub data without touching repositories or work directories."""
    now = now or datetime.now(timezone.utc)
    removed_attachments = 0
    removed_projects = 0
    attachment_cutoff = now - timedelta(hours=24)
    root = (Path(Settings().data_dir).expanduser().resolve() / "attachments").resolve()

    candidates = list(db.scalars(select(Attachment)))
    for attachment in candidates:
        expired = (attachment.sent_at is not None and attachment.expires_at is not None and attachment.expires_at <= now)
        abandoned = attachment.sent_at is None and attachment.created_at <= attachment_cutoff
        if not (expired or abandoned):
            continue
        try:
            path = Path(attachment.storage_path).resolve()
            if path.parent == root:
                path.unlink(missing_ok=True)
            db.delete(attachment)
            db.commit()
            removed_attachments += 1
        except OSError as exc:
            db.rollback()
            db.add(ProjectLifecycleError(
                id=str(uuid4()), project_id=attachment.project_id,
                operation="attachment-purge", error=str(exc)[:500],
            ))
            db.commit()

    project_cutoff = now - timedelta(days=14)
    projects = list(db.scalars(select(Project).where(Project.deleted_at.is_not(None), Project.deleted_at <= project_cutoff)))
    for project in projects:
        try:
            session_ids = list(db.scalars(select(Session.id).where(Session.project_id == project.id)))
            if session_ids:
                # Retention is the one operation allowed to delete append-only events: the
                # trigger lets DELETE through only while this transaction sets aihub.purge (0012).
                db.execute(text("SET LOCAL aihub.purge = 'on'"))
                db.execute(delete(AgentEvent).where(AgentEvent.session_id.in_(session_ids)))
            db.execute(delete(Attachment).where(Attachment.project_id == project.id))
            db.execute(delete(Task).where(Task.project_id == project.id))
            db.execute(delete(Session).where(Session.project_id == project.id))
            db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
            db.delete(project)
            db.commit()
            removed_projects += 1
        except Exception as exc:  # keep the periodic job alive and retain an audit record
            db.rollback()
            db.add(ProjectLifecycleError(
                id=str(uuid4()), project_id=project.id,
                operation="project-purge", error=str(exc)[:500],
            ))
            db.commit()
    return {"attachments": removed_attachments, "projects": removed_projects}
