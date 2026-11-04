"""The panel's file browser: a project's folder, or one session's folder (agents leave screenshots there).

Like the instructions editor, the hub only queues a request for the project's worker and hands the answer back
once: the worker resolves every path inside the project's folder, and the file is not kept here (the request
row is removed when its answer is collected, rows older than an hour are dropped).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete

from ..auth import current_user, db_dep
from ..deps import mark_offline, project_or_404
from ..models import Session, Worker, WorkerRequest

router = APIRouter(tags=["files"])

KIND = "files"


class FilesIn(BaseModel):
    op: str = Field(pattern=r"^(list|read)$")
    path: str = Field(default="", max_length=1000)


@router.post("/sessions/{session_id}/files")
def session_files(session_id: str, data: FilesIn, user=Depends(current_user), db=Depends(db_dep)):
    """A session's own folder (an executor's worktree, say): where it left the files it links to."""
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    if not session.workdir:
        raise HTTPException(409, "у сессии нет рабочей папки")
    mark_offline(db)
    worker = db.get(Worker, session.worker_id) if session.worker_id else None
    if not worker or worker.status != "online":
        raise HTTPException(409, f"воркер {session.worker_id} не в сети — файлы лежат на нём")
    # `path` keeps who asked: the worker's answer replaces `response` later; the folder is the session's own.
    request = WorkerRequest(worker_id=worker.id, session_id=session.id, kind=KIND, path=user.id,
                            response=data.model_dump())
    db.add(request)
    db.commit()
    return {"request_id": request.id}


@router.post("/projects/{project_id}/files")
def project_files(project_id: str, data: FilesIn, user=Depends(current_user), db=Depends(db_dep)):
    """The project's folder, where its agents work: on the worker of its latest session that is online."""
    from .instructions import _project_worker

    project = project_or_404(db, user, project_id)
    root = (project.allowed_paths or [None])[0]
    if not root:
        raise HTTPException(409, "у проекта не указана папка")
    # The root comes from the project record, never from the panel's request.
    request = WorkerRequest(worker_id=_project_worker(db, project), kind=KIND, path=user.id,
                            response={**data.model_dump(), "workdir": root})
    db.add(request)
    db.commit()
    return {"request_id": request.id}


@router.get("/files/requests/{request_id}")
def files_result(request_id: str, user=Depends(current_user), db=Depends(db_dep)):
    now = datetime.now(timezone.utc)
    db.execute(delete(WorkerRequest).where(WorkerRequest.kind == KIND, WorkerRequest.created_at < now - timedelta(hours=1)))
    request = db.get(WorkerRequest, request_id)
    if not request or request.kind != KIND or request.path != user.id:
        db.commit()
        raise HTTPException(404, "request not found")
    if request.status in {"queued", "running"}:
        db.commit()
        return {"status": request.status}
    answer = dict(request.response or {})
    db.delete(request)
    db.commit()
    if answer.get("error") is not None:
        return {"status": "failed", "error": str(answer["error"])}
    return {"status": "completed", "result": answer.get("result")}
