import time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, update

from ..auth import current_user, db_dep, issue_scoped_token, worker_principal
from ..config import Settings
from ..deps import project_or_404
from ..models import AgentEvent, Attachment, Project, Session, Task, Worker, WorkerCapability, WorkerRequest
from ..models import AccountProfile
from .attachments import _storage_root
from ..system_settings import get_setting
from ..orchestration.workspace import InvalidWorkspacePath
from ..orchestration.notifications import notify_users

router = APIRouter(tags=["assignments"])


def _assignment_config_dir(db, session: Session) -> str | None:
    if not session.account_profile_id:
        return None
    account = db.get(AccountProfile, session.account_profile_id)
    return account.config_dir if account and account.worker_id == session.worker_id else None


# --- Worker subscription status ---
@router.get("/workers/{worker_id}/accounts")
def worker_accounts(worker_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    if principal.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    return [
        {"id": account.id, "kind": account.kind, "config_dir": account.config_dir,
         "login_watch_until": account.login_watch_until}
        for account in db.scalars(
            select(AccountProfile).where(AccountProfile.worker_id == worker_id)
        )
    ]


@router.post("/workers/{worker_id}/recover")
def recover_worker_sessions(worker_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    """Fail sessions left behind by a worker process that was restarted."""
    if principal.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    sessions = list(db.scalars(
        select(Session).where(
            Session.worker_id == worker_id,
            Session.status.in_({"starting", "running"}),
        )
    ))
    for session in sessions:
        session.status = "failed"
        session.status_source = "heartbeat"
        db.add(AgentEvent(
            session_id=session.id,
            kind="session.status",
            source="heartbeat",
            payload={"status": "failed", "reason": "worker restarted"},
        ))
        notify_users(db, "session", "Session failed", body="worker restarted", session_id=session.id)
    db.commit()
    return {"failed": len(sessions)}


@router.get("/{worker_id}/assignments")
def assignments(worker_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    if principal.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    return [
        {
            **{column.name: getattr(s, column.name) for column in Session.__table__.columns},
            # The worker must receive the selected profile atomically with the conversation ref.
            "config_dir": _assignment_config_dir(db, s),
        }
        for s in db.scalars(
            select(Session)
            .where(Session.worker_id == worker_id, Session.status == "queued")
            .order_by(Session.created_at)
        ).all()
    ]


@router.post("/assignments/{assignment_id}/claim")
def claim(assignment_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    session = db.get(Session, assignment_id)
    if not session or session.worker_id != principal.worker_id:
        raise HTTPException(404, "assignment not found")
    result = db.execute(
        update(Session)
        .where(Session.id == assignment_id, Session.status == "queued")
        .values(status="starting")
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "assignment already claimed")
    db.commit()
    db.refresh(session)
    project = db.get(Project, session.project_id)
    task = db.get(Task, session.task_id) if session.task_id else None
    result = {
        "id": session.id,
        "task_id": session.task_id,
        "project_id": session.project_id,
        "worker_id": session.worker_id,
        "engine": session.engine,
        "provider": session.provider,
        "model": session.model,
        "workdir": session.workdir,
        "branch": session.branch,
        "account_profile_id": session.account_profile_id,
        "config_dir": _assignment_config_dir(db, session),
        "workspace_ref": session.workspace_ref,
        "title": session.title,
        "engine_session_ref": session.engine_session_ref,
        "context_tokens": session.context_tokens,
        "context_fresh": session.context_fresh,
        "mcp_config": session.mcp_config,
        "chat_id": session.chat_id,
        # Orchestrator mode: the worker gives orchestrators the orch_* MCP tools and executors a git worktree.
        "role": session.role,
        "permission_mode": session.permission_mode,
        "orchestration": session.orchestration,
        "parent_session_id": session.parent_session_id,
        "allowed_paths": project.allowed_paths if project else [],
        "task_body": task.body if task else "",
        "task_title": task.title if task else None,
    }
    mcp_config = session.mcp_config or {}
    if mcp_config.get("user_id") and mcp_config.get("mcpServers"):
        from ..models import User
        owner = db.get(User, mcp_config["user_id"])
        if owner:
            scopes = {"knowledge:read", "knowledge:draft"}
            if session.role == "orchestrator":
                scopes.add(f"orchestrate:{session.id}")
            if session.permission_mode == "ask":
                scopes.add(f"permit:{session.id}")
            token = issue_scoped_token(owner, scopes, settings=Settings())
            result["knowledge_token"] = token.access_token
            result["hub_token"] = token.access_token
            result["token_expires_in"] = token.expires_in
            result["hub_url"] = get_setting(db, "public_url")
    return result


@router.post("/assignments/{assignment_id}/token")
def renew_assignment_token(assignment_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    """Exchange a worker token for a fresh scoped memory/orchestration token."""
    session = db.get(Session, assignment_id)
    if not session or session.worker_id != principal.worker_id:
        raise HTTPException(404, "assignment not found")
    if session.status in {"completed", "failed", "offline"}:
        raise HTTPException(409, "assignment is no longer active")
    config = session.mcp_config or {}
    user_id = config.get("user_id")
    if not user_id:
        raise HTTPException(409, "assignment has no scoped principal")
    from ..models import User
    owner = db.get(User, user_id)
    if not owner:
        raise HTTPException(404, "assignment principal not found")
    scopes = {"knowledge:read", "knowledge:draft"}
    if session.role == "orchestrator":
        scopes.add(f"orchestrate:{session.id}")
    if session.permission_mode == "ask":
        scopes.add(f"permit:{session.id}")
    token = issue_scoped_token(owner, scopes, settings=Settings())
    return {"access_token": token.access_token, "token_type": "bearer", "expires_in": token.expires_in, "hub_url": get_setting(db, "public_url")}


@router.get("/assignments/{assignment_id}")
def assignment(assignment_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    session = db.get(Session, assignment_id)
    if not session or session.worker_id != principal.worker_id:
        raise HTTPException(404, "assignment not found")
    return session


@router.get("/assignments/{assignment_id}/events")
def assignment_events(
    assignment_id: str,
    after: int = Query(0),
    principal=Depends(worker_principal),
    db=Depends(db_dep),
):
    session = db.get(Session, assignment_id)
    if not session or session.worker_id != principal.worker_id:
        raise HTTPException(404, "assignment not found")
    return list(
        db.scalars(
            select(AgentEvent)
            .where(AgentEvent.session_id == assignment_id, AgentEvent.cursor > after)
            .order_by(AgentEvent.cursor)
        )
    )


def _worker_attachment(session_id: str, attachment_id: str, worker_id: str, db):
    session = db.get(Session, session_id)
    if not session or session.worker_id != worker_id:
        raise HTTPException(404, "assignment not found")
    attachment = db.get(Attachment, attachment_id)
    if not attachment or attachment.session_id != session_id:
        raise HTTPException(404, "attachment not found")
    return attachment


@router.get("/assignments/{assignment_id}/attachments")
def assignment_attachments(
    assignment_id: str, principal=Depends(worker_principal), db=Depends(db_dep)
):
    """Return attachment metadata to the assigned worker without exposing user auth."""
    session = db.get(Session, assignment_id)
    if not session or session.worker_id != principal.worker_id:
        raise HTTPException(404, "assignment not found")
    return [
        {
            "id": item.id,
            "original_name": item.original_name,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
        }
        for item in db.scalars(
            select(Attachment)
            .where(Attachment.session_id == assignment_id)
            .order_by(Attachment.created_at, Attachment.id)
        )
    ]


@router.get("/assignments/{assignment_id}/attachments/{attachment_id}")
def download_assignment_attachment(
    assignment_id: str,
    attachment_id: str,
    principal=Depends(worker_principal),
    db=Depends(db_dep),
):
    attachment = _worker_attachment(assignment_id, attachment_id, principal.worker_id, db)
    path = Path(attachment.storage_path).resolve()
    if not path.is_file() or path.parent != _storage_root().resolve():
        raise HTTPException(404, "attachment content not found")
    return FileResponse(path, media_type=attachment.mime_type)


@router.post("/workers/{worker_id}/capabilities")
def capabilities(
    worker_id: str, payload: dict, principal=Depends(worker_principal), db=Depends(db_dep)
):
    if principal.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    from ..models import Worker

    worker = db.get(Worker, worker_id)
    if not worker:
        raise HTTPException(404, "worker not found")
    labels = [f"engine:{name}" for name in payload.get("engines", {})]
    if payload.get("workspace_url"):
        labels.append("codeman")
    worker.labels = sorted(set((worker.labels or []) + labels))
    snapshot = db.get(WorkerCapability, worker_id) or WorkerCapability(worker_id=worker_id)
    snapshot.capabilities = payload.get("engines", {})
    snapshot.workspace_url = payload.get("workspace_url")
    db.add(snapshot)
    db.commit()
    return {"ok": True, "worker_id": worker_id, "engines": payload.get("engines", {})}


@router.get("/workers/{worker_id}")
def worker_details(worker_id: str, user=Depends(current_user), db=Depends(db_dep)):
    capability = db.get(WorkerCapability, worker_id)
    if not capability:
        raise HTTPException(404, "worker not found")
    return {
        "worker_id": worker_id,
        "capabilities": capability.capabilities,
        "workspace_url": capability.workspace_url,
    }


@router.get("/workers/{worker_id}/requests/next")
def next_request(worker_id: str, principal=Depends(worker_principal), db=Depends(db_dep)):
    if principal.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    request = db.scalars(
        select(WorkerRequest)
        .where(WorkerRequest.worker_id == worker_id, WorkerRequest.status == "queued")
        .order_by(WorkerRequest.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if not request:
        return None
    request.status = "running"
    db.commit()
    session = db.get(Session, request.session_id) if request.session_id else None
    return {
        "id": request.id,
        "kind": request.kind,
        "path": request.path,
        "session_id": request.session_id,
        "workdir": session.workdir if session else None,
        # Account control requests also carry their validated account/engine parameters.
        "response": request.response if request.kind in {
            "limits_refresh", "git_merge", "account_adopt_login", "account_delete"
        } else None,
    }


@router.post("/workers/{worker_id}/requests/{request_id}/response")
def request_response(
    worker_id: str,
    request_id: str,
    payload: dict,
    principal=Depends(worker_principal),
    db=Depends(db_dep),
):
    if principal.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    request = db.get(WorkerRequest, request_id)
    if not request or request.worker_id != worker_id:
        raise HTTPException(404, "worker request not found")
    request.status = "completed" if payload.get("error") is None else "failed"
    if request.kind == "git_merge":
        from .orchestration_view import finish_merge

        finish_merge(db, request, payload)  # reads the merge parameters before they are replaced
    request.response = payload
    request.completed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


def _workspace_request(kind: str, session_id: str, path: str | None, user, db):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    worker = db.get(Worker, session.worker_id)
    if not worker or worker.status == "offline":
        raise HTTPException(503, "worker offline")
    try:
        # Reject malformed paths before putting them in the queue.
        from ..orchestration.workspace import safe_path

        safe_path(session.workdir, path or ".")
    except (InvalidWorkspacePath, OSError) as exc:
        raise HTTPException(403, "path is outside workspace") from exc
    request = WorkerRequest(
        worker_id=session.worker_id, session_id=session.id, kind=kind, path=path
    )
    db.add(request)
    db.commit()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        db.expire_all()
        current = db.get(WorkerRequest, request.id)
        if current and current.status in {"completed", "failed"}:
            if current.status == "failed":
                raise HTTPException(502, current.response.get("error", "worker request failed"))
            return current.response.get("result", current.response)
        time.sleep(0.05)
    raise HTTPException(504, "worker did not respond within 10 seconds")


@router.get("/sessions/{session_id}/files")
def session_files(
    session_id: str, path: str = Query("."), user=Depends(current_user), db=Depends(db_dep)
):
    return _workspace_request("list", session_id, path, user, db)


@router.get("/sessions/{session_id}/file")
def session_file(
    session_id: str, path: str = Query(...), user=Depends(current_user), db=Depends(db_dep)
):
    return _workspace_request("file", session_id, path, user, db)


@router.get("/sessions/{session_id}/git/status")
def session_git_status(session_id: str, user=Depends(current_user), db=Depends(db_dep)):
    return _workspace_request("git_status", session_id, None, user, db)


@router.get("/sessions/{session_id}/git/diff")
def session_git_diff(
    session_id: str,
    path: str = Query(...),
    staged: int = Query(0, ge=0, le=1),
    user=Depends(current_user),
    db=Depends(db_dep),
):
    # The staged selector is part of the public contract; the worker only exposes read-only diff.
    return _workspace_request(
        "git_diff_staged" if staged else "git_diff", session_id, path, user, db
    )


@router.get("/sessions/{session_id}/git/log")
def session_git_log(
    session_id: str,
    limit: int = Query(20, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(db_dep),
):
    return _workspace_request("git_log", session_id, None, user, db)
