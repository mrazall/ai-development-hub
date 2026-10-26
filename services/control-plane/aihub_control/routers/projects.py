from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from ..auth import current_user, db_dep, write_user
from ..models import AgentEvent, AuditLog, Attachment, Project, ProjectMember, Session, Task, Worker, WorkerRequest
from ..schemas import DeletionImpact, ProjectIn, ProjectOut
from ..deps import project_or_404

router = APIRouter(prefix="/projects", tags=["projects"])


def _enqueue_mkdir(db, project: Project, previous: list | None = None) -> None:
    """Ask workers to create the project folder; never blocks project create/update."""
    path = project.allowed_paths[0] if project.allowed_paths else None
    if not path or project.is_personal or (previous and previous[:1] == [path]):
        return
    # Projects are not bound to a worker: queue for every online worker. Offline ones are
    # skipped (the queue would go stale); the folder is created on the next save instead.
    for worker in db.scalars(select(Worker).where(Worker.status != "offline")):
        db.add(WorkerRequest(worker_id=worker.id, kind="mkdir", path=path))


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectIn, user=Depends(write_user), db=Depends(db_dep)):
    project = Project(**data.model_dump())
    db.add(project)
    _enqueue_mkdir(db, project)
    db.add(AuditLog(user_id=user.id, action="project.create", target=project.id))
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(view: str = Query("active", pattern="^(active|archived|trash|all)$"), user=Depends(current_user), db=Depends(db_dep)):
    query = select(Project)
    if view == "active":
        query = query.where(Project.archived_at.is_(None), Project.deleted_at.is_(None), Project.is_personal.is_(False))
    elif view == "archived":
        query = query.where(Project.archived_at.is_not(None), Project.deleted_at.is_(None))
    elif view == "trash":
        query = query.where(Project.deleted_at.is_not(None))
    if user.role != "admin":
        query = query.where(
            (Project.visibility.in_(["shared", "public"]))
            | Project.id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
            )
        )
    return list(db.scalars(query))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, user=Depends(current_user), db=Depends(db_dep)):
    return project_or_404(db, user, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, data: ProjectIn, user=Depends(write_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    previous = list(project.allowed_paths or [])
    for key, value in data.model_dump().items():
        if key != "id":
            setattr(project, key, value)
    _enqueue_mkdir(db, project, previous)
    db.add(AuditLog(user_id=user.id, action="project.update", target=project_id))
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    active = db.scalar(select(func.count(Session.id)).where(Session.project_id == project_id, Session.status.not_in(["completed", "failed", "offline"]))) or 0
    if active:
        raise HTTPException(409, "project has active sessions; stop them before deleting")
    project.deleted_at = datetime.now(timezone.utc)
    project.archived_at = None
    db.add(AuditLog(user_id=user.id, action="project.delete", target=project_id))
    db.commit()


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(project_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    project.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/restore", response_model=ProjectOut)
def restore_project(project_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project = db.get(Project, project_id)
    if not project or not can_restore(project):
        raise HTTPException(404, "project not found or recovery window expired")
    project.deleted_at = None
    project.archived_at = None
    db.commit()
    db.refresh(project)
    return project


def can_restore(project: Project) -> bool:
    return project.deleted_at is None or datetime.now(timezone.utc) - project.deleted_at <= timedelta(days=14)


@router.get("/{project_id}/deletion-impact", response_model=DeletionImpact)
def deletion_impact(project_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project_or_404(db, user, project_id)
    sessions = select(Session.id).where(Session.project_id == project_id)
    active = db.scalar(select(func.count(Session.id)).where(Session.project_id == project_id, Session.status.not_in(["completed", "failed", "offline"]))) or 0
    return DeletionImpact(
        tasks=db.scalar(select(func.count(Task.id)).where(Task.project_id == project_id)) or 0,
        sessions=db.scalar(select(func.count(Session.id)).where(Session.project_id == project_id)) or 0,
        active_sessions=active,
        events=db.scalar(select(func.count(AgentEvent.cursor)).where(AgentEvent.session_id.in_(sessions))) or 0,
        attachments=db.scalar(select(func.count(Attachment.id)).where(Attachment.project_id == project_id)) or 0,
        knowledge=0,
        warning="Не удаляются: репозиторий, рабочие файлы, vault и бэкапы.",
    )


@router.put("/{project_id}/members/{user_id}", status_code=204)
def add_member(project_id: str, user_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project_or_404(db, user, project_id)
    if not db.get(ProjectMember, {"user_id": user_id, "project_id": project_id}):
        db.add(ProjectMember(user_id=user_id, project_id=project_id))
        db.commit()
