from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ..auth import current_user, db_dep
from ..deps import is_admin, visible_events
from ..models import Project, ProjectMember, Session, Task, Worker
from ..schemas import EventOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(user=Depends(current_user), db=Depends(db_dep)):
    projects_query = select(Project)
    if not is_admin(user):
        projects_query = projects_query.where(
            (Project.visibility.in_(["shared", "public"]))
            | Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
        )
    projects = list(db.scalars(projects_query))
    project_ids = [project.id for project in projects]
    task_rows = db.execute(select(Task.status, func.count(Task.id)).where(Task.project_id.in_(project_ids)).group_by(Task.status)).all() if project_ids else []
    session_rows = db.execute(select(Session.status, func.count(Session.id)).where(Session.project_id.in_(project_ids)).group_by(Session.status)).all() if project_ids else []
    worker_rows = db.execute(select(Worker.status, func.count(Worker.id)).group_by(Worker.status)).all()
    recent = visible_events(db, user, 0, limit=20, newest=True)
    return {"projects": len(projects), "tasks": dict(task_rows), "sessions": dict(session_rows), "workers": dict(worker_rows), "events": [EventOut.model_validate(event).model_dump(mode="json") for event in recent], "services": {"api": "ok", "database": "ok", "knowledge": "unknown"}}
