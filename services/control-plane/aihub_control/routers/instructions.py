"""Agent instructions from the panel: AGENTS.md, CLAUDE.md and skills, read and edited on a worker.

The hub only queues a request for a worker and hands its answer back once: the files live on the worker, the
worker checks every path itself, and the file contents are neither stored nor logged here (the request row is
removed when its answer is collected; the audit log keeps who changed which file, with hashes, no text).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from ..auth import current_user, db_dep
from ..deps import is_admin, mark_offline, project_or_404
from ..models import AuditLog, Session, Worker, WorkerRequest

router = APIRouter(tags=["instructions"])

KIND = "instructions"
MAX_BYTES = 256 * 1024
WRITE_OPS = {"write", "delete", "restore"}
_SKILL = r"[a-z0-9][a-z0-9-]{0,63}"
PROJECT_PATH = re.compile(rf"^(AGENTS\.md|CLAUDE\.md|\.claude/skills/{_SKILL}/SKILL\.md)$")
WORKER_PATH = re.compile(rf"^(accounts/{_SKILL}/)?(claude/CLAUDE\.md|claude/skills/{_SKILL}/SKILL\.md|codex/AGENTS\.md)$")


class InstructionsIn(BaseModel):
    op: str = Field(pattern=r"^(list|read|write|delete|backups|restore)$")
    path: str | None = Field(default=None, max_length=300)
    content: str | None = None
    base_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    backup: str | None = Field(default=None, max_length=40)


def _check(data: InstructionsIn, pattern: re.Pattern, user) -> None:
    if data.op != "list" and not (data.path and pattern.match(data.path)):
        raise HTTPException(422, "путь вне разрешённых")
    if data.op in WRITE_OPS and getattr(user, "role", None) == "viewer":
        raise HTTPException(403, "только чтение")
    if data.content is not None and len(data.content.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "файл больше 256 КБ")


def _queue(db, worker_id: str, user, params: dict) -> dict:
    # `path` keeps who asked and for which file: the worker's answer replaces `response` later.
    request = WorkerRequest(worker_id=worker_id, kind=KIND, path=f"{user.id}|{params.get('path') or ''}",
                            response=params)
    db.add(request)
    db.commit()
    return {"request_id": request.id, "worker_id": worker_id}


def _project_worker(db, project) -> str:
    """The worker of the project's latest session if it is online, else any online worker."""
    mark_offline(db)
    online = set(db.scalars(select(Worker.id).where(Worker.status == "online")))
    latest = db.scalars(
        select(Session.worker_id).where(Session.project_id == project.id).order_by(Session.created_at.desc()).limit(20)
    ).all()
    for worker_id in latest:
        if worker_id in online:
            return worker_id
    if online:
        return min(online)
    raise HTTPException(409, "нет воркера в сети — файлы проекта лежат на воркерах")


@router.post("/projects/{project_id}/instructions")
def project_instructions(project_id: str, data: InstructionsIn, user=Depends(current_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    _check(data, PROJECT_PATH, user)
    if data.op in {"backups", "restore"}:
        raise HTTPException(422, "у файлов проекта история — в git")
    root = (project.allowed_paths or [None])[0]
    if not root:
        raise HTTPException(409, "у проекта не указана папка")
    params = {**data.model_dump(exclude_none=True), "scope": "project", "project_root": root,
              "target": f"project:{project.id}"}
    return _queue(db, _project_worker(db, project), user, params)


@router.post("/workers/{worker_id}/instructions")
def worker_instructions(worker_id: str, data: InstructionsIn, user=Depends(current_user), db=Depends(db_dep)):
    # The worker's shared files act on every account of that machine: administrators only.
    if not is_admin(user):
        raise HTTPException(403, "только для администратора")
    _check(data, WORKER_PATH, user)
    mark_offline(db)
    worker = db.get(Worker, worker_id)
    if not worker:
        raise HTTPException(404, "worker not found")
    if worker.status != "online":
        raise HTTPException(409, f"воркер {worker_id} не в сети")
    params = {**data.model_dump(exclude_none=True), "scope": "worker", "target": f"worker:{worker_id}"}
    return _queue(db, worker_id, user, params)


@router.get("/instructions/requests/{request_id}")
def instruction_result(request_id: str, user=Depends(current_user), db=Depends(db_dep)):
    """The worker's answer, given once: the row (it may hold a file's text) is removed when it is collected."""
    now = datetime.now(timezone.utc)
    db.execute(delete(WorkerRequest).where(WorkerRequest.kind == KIND, WorkerRequest.created_at < now - timedelta(hours=1)))
    request = db.get(WorkerRequest, request_id)
    if not request or request.kind != KIND:
        raise HTTPException(404, "request not found")
    asker, _, file_path = (request.path or "").partition("|")
    if asker != user.id:
        raise HTTPException(404, "request not found")
    if request.status in {"queued", "running"}:
        db.commit()
        return {"status": request.status}
    answer = dict(request.response or {})
    db.delete(request)
    result, error = answer.get("result"), answer.get("error")
    if error is None and isinstance(result, dict) and "sha256" in result:
        db.add(AuditLog(user_id=user.id, action="instructions.change", target=f"{request.worker_id}:{file_path}",
                        details={k: result.get(k) for k in ("commit", "backup", "snapshot", "sha256")}))
    db.commit()
    if error is not None:
        text = str(error)
        status = 409 if "conflict" in text else 422
        return {"status": "failed", "error": text.replace("conflict: ", ""), "code": status}
    return {"status": "completed", "result": result}
