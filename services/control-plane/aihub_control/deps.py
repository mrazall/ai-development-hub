import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from .models import AgentEvent, Project, ProjectMember, Session, User, Worker
from .rbac import can_access_project


def project_or_404(db, user, project_id):
    project = db.get(Project, project_id)
    if not project or not can_access_project(db, user, project_id):
        raise HTTPException(404, "project not found")
    return project


def is_admin(principal):
    return isinstance(principal, User) and principal.role == "admin"


# What a chat view shows. A long agent run is ~95 % engine bookkeeping (thinking ticks, tool progress,
# streamed partials); without this filter the latest N events held only a couple of messages.
CHAT_KINDS = ("message", "session.status", "diff", "approval.request")
ACTIVITY_KINDS = (*CHAT_KINDS, "tool.call", "tool.result", "output")
CHAT_RAW_TYPES = ("assistant", "item.completed")
EVENT_VIEWS = ("chat", "activity", "events")


def visible_events(db, principal, after, session_id=None, limit=500, newest=False, view=None, session_ids=None):
    """Events after `after`, oldest first; with newest=True — the latest `limit` events (still returned oldest first).
    view: "chat" — what a conversation shows (final, non-technical messages, statuses, diffs, approvals);
    "activity" — that plus commands, their results and plain output (the agent terminal);
    "events" — everything except streamed partial messages (the events log)."""
    query = (
        select(AgentEvent)
        .join(Session, AgentEvent.session_id == Session.id)
        .join(Project, Session.project_id == Project.id)
        .where(AgentEvent.cursor > after)
        .order_by(AgentEvent.cursor.desc() if newest else AgentEvent.cursor)
        .limit(limit)
    )
    if session_id:
        query = query.where(AgentEvent.session_id == session_id)
    if session_ids:
        query = query.where(AgentEvent.session_id.in_(session_ids))
    if view in EVENT_VIEWS:
        raw_type = AgentEvent.payload["raw_type"].as_string()
        partial = AgentEvent.payload["partial"].as_string()
        query = query.where(or_(partial.is_(None), partial != "true"))
        if view in ("chat", "activity"):
            query = query.where(
                AgentEvent.kind.in_(CHAT_KINDS if view == "chat" else ACTIVITY_KINDS),
                or_(AgentEvent.kind != "message", raw_type.is_(None), raw_type.in_(CHAT_RAW_TYPES)),
                # Engine bookkeeping on the output channel (thinking ticks, tool progress) carries a raw_type.
                or_(AgentEvent.kind != "output", raw_type.is_(None)),
            )
    if not is_admin(principal):
        query = query.where(
            (Project.visibility.in_(["shared", "public"]))
            | Project.id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == principal.id)
            )
        )
    rows = list(db.scalars(query))
    return rows[::-1] if newest else rows


def mark_offline(db):
    now = datetime.now(timezone.utc)
    workers = db.scalars(select(Worker)).all()
    for worker in workers:
        if (
            worker.last_heartbeat_at
            and (now - worker.last_heartbeat_at).total_seconds() <= worker.lease_ttl_s
        ):
            continue
        worker.status = "offline"
        sessions = db.scalars(select(Session).where(Session.worker_id == worker.id)).all()
        for session in sessions:
            # Queued sessions have no process yet; marking them offline would leave them unclaimable.
            if session.status in {"queued", "completed", "failed", "offline"}:
                continue
            session.status = "offline"
            session.status_source = "heartbeat"
            db.add(
                AgentEvent(
                    session_id=session.id,
                    kind="session.status",
                    source="heartbeat",
                    payload={"status": "offline"},
                )
            )
    db.commit()


async def offline_loop():
    from .db import get_session_factory

    while True:
        await asyncio.sleep(10)
        try:
            _, factory = get_session_factory()
            db = factory()
            try:
                mark_offline(db)
            finally:
                db.close()
        except SQLAlchemyError:
            continue
