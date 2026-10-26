from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ..auth import current_user, db_dep
from ..deps import project_or_404
from ..models import AgentEvent, Project, Session, Task

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
def graph(
    project_id: str,
    root_session_id: str | None = Query(None),
    user=Depends(current_user),
    db=Depends(db_dep),
):
    project_or_404(db, user, project_id)
    sessions = list(
        db.scalars(
            select(Session).where(Session.project_id == project_id).order_by(Session.created_at)
        ).all()
    )
    if root_session_id:
        allowed = {root_session_id}
        changed = True
        while changed:
            changed = False
            for item in sessions:
                if item.parent_session_id in allowed and item.id not in allowed:
                    allowed.add(item.id)
                    changed = True
        sessions = [item for item in sessions if item.id in allowed]
    tasks = {
        task.id: task
        for task in db.scalars(select(Task).where(Task.project_id == project_id)).all()
    }
    latest_rows = (
        db.execute(
            select(AgentEvent.session_id, AgentEvent.kind, AgentEvent.ts)
            .where(AgentEvent.session_id.in_([s.id for s in sessions]))
            .order_by(AgentEvent.session_id, AgentEvent.ts.desc())
            .distinct(AgentEvent.session_id)
        ).all()
        if sessions
        else []
    )
    latest = {}
    for row in latest_rows:
        latest.setdefault(row.session_id, {"kind": row.kind, "ts": row.ts})
    nodes = [
        {
            "id": s.id,
            "type": "session",
            "title": s.title,
            "engine": s.engine,
            "model": s.model,
            "account_profile_id": s.account_profile_id,
            "worker_id": s.worker_id,
            "task_id": s.task_id,
            "status": s.status,
            "started_at": s.created_at,
            "updated_at": s.updated_at,
            "duration_s": max(0, (s.updated_at - s.created_at).total_seconds())
            if s.updated_at and s.created_at
            else None,
            "latest_event": latest.get(s.id),
        }
        for s in sessions
    ]
    edges = [
        {"from": s.parent_session_id, "to": s.id, "type": "parent_session"}
        for s in sessions
        if s.parent_session_id
    ]
    for task in tasks.values():
        edges.extend(
            {"from": dep, "to": task.id, "type": "depends_on"} for dep in (task.depends_on or [])
        )
    return {"nodes": nodes, "edges": edges}
