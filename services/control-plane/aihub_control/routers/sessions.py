import json
import re
from datetime import datetime, timezone

import jwt
from fastapi.security import HTTPAuthorizationCredentials
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy import select

from ..analytics.runs import create_run, latest_run, update_run
from ..auth import bearer, current_principal, current_user, db_dep, write_user
from ..config import Settings
from ..deps import project_or_404
from sqlalchemy import delete, text

from ..models import AccountProfile, AgentEvent, Task, User, Approval, Attachment, Notification, Project, ProjectMember, Session, WorkerRequest, WorkerToken
from ..redaction import redact
from ..schemas import ContinueIn, ContinueOnAccountIn, EventIn, EventOut, PermissionRequestIn, SessionIn, SessionOut, StatusIn
from ..deps import is_admin
from ..state import validate_transition
from ..orchestration.notifications import notify_users
from ..approvals.service import create_from_event, expire_approval
from ..orchestration.auto_resume import CROSS_ACCOUNT_RESUME_MODE, resume_session, schedule_if_limited
from .chats import _mcp_config
from .limits import account_limits

router = APIRouter(prefix="/sessions", tags=["sessions"])


# A subscription profile is the login of one CLI: Codex started with a Claude profile has no OpenAI login (401).
ENGINE_OF_ACCOUNT = {"claude_code_subscription": "claude_code", "codex_subscription": "codex"}
_LOGIN_FILE_PATH = re.compile(r"(?:~|/)[^\s\"']*(?:\.credentials\.json|\.claude\.json|(?:^|/)auth\.json)")


def _safe_resume_summary(text: str) -> str:
    """Keep continuation context useful without copying credentials or login-file paths."""
    safe, _ = redact(text[:500])
    return _LOGIN_FILE_PATH.sub("[login file path redacted]", safe)


def _check_engine_matches_account(db, engine: str, account_profile_id: str | None) -> None:
    account = db.get(AccountProfile, account_profile_id) if account_profile_id else None
    expected = ENGINE_OF_ACCOUNT.get(account.kind) if account else None
    if expected and engine != expected and not engine.startswith("mock"):  # mock engines need no login
        raise HTTPException(422, f"аккаунт {account.id} работает только с движком {expected}, выбран {engine}")


def _check_account_on_worker(db, worker_id: str, account_profile_id: str | None) -> None:
    """A login lives in a profile folder on one machine: another worker could never run the session."""
    account = db.get(AccountProfile, account_profile_id) if account_profile_id else None
    if account and account.worker_id and account.worker_id != worker_id:
        raise HTTPException(422, f"аккаунт {account.id} вошёл на воркере {account.worker_id}, а не на {worker_id}")


def _sync_task_status(db, session: Session, status: str) -> None:
    """A task follows its session: in progress while it runs, in review when it finishes (a person checks the
    result). «done» and «cancelled» are the owner's and are never overwritten; an orchestrator's executors do
    not move the shared task. Tasks used to stay «draft» forever."""
    if not session.task_id or session.role == "executor":
        return
    task = db.get(Task, session.task_id)
    if not task or task.status in {"done", "cancelled"}:
        return
    if status in {"starting", "running"} and task.status != "in_progress":
        task.status = "in_progress"
    elif status == "completed" and task.status == "in_progress":
        task.status = "review"


@router.post("", response_model=SessionOut)
def create_session(data: SessionIn, user=Depends(write_user), db=Depends(db_dep)):
    project_or_404(db, user, data.project_id)
    _check_engine_matches_account(db, data.engine, data.account_profile_id)
    _check_account_on_worker(db, data.worker_id, data.account_profile_id)
    session = Session(**data.model_dump(exclude={"hold", "effort"}), **({"status": "draft"} if data.hold else {}))
    if data.effort:  # the worker reads it from mcp_config, like a chat's effort
        session.mcp_config = {**(session.mcp_config or {}), "effort": data.effort}
    if data.permission_mode == "ask" and data.engine == "claude_code" and not session.mcp_config:
        # "Ask" goes through the hub MCP server (its permission tool); the worker exchanges the user id for a
        # short-lived token scoped to this session's permission requests.
        session.mcp_config = {"mcpServers": _mcp_config()["mcpServers"], "user_id": user.id}
    db.add(session)
    if not data.hold:
        create_run(db, session, "initial")
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
def list_sessions(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    user=Depends(current_user),
    db=Depends(db_dep),
):
    query = select(Session).order_by(Session.updated_at.desc()).limit(limit)
    if project_id:
        query = query.where(Session.project_id == project_id)
    if status:
        query = query.where(Session.status == status)
    if not is_admin(user):
        query = query.join(Project, Session.project_id == Project.id).where(
            Project.visibility.in_(["shared", "public"])
            | Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
        )
    return list(db.scalars(query))


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: str, user=Depends(current_user), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    return session


@router.patch("/{session_id}/status", response_model=SessionOut)
def set_status(session_id: str, data: StatusIn, user=Depends(write_user), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    try:
        validate_transition(session.status, data.status.value)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.status = data.status.value
    if data.status.value in {"completed", "failed"}:
        notify_users(db, "session", f"Session {data.status.value}", session_id=session.id)
    db.commit()
    return session


@router.post("/{session_id}/start", response_model=SessionOut)
def start_session(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    """Queue a session created with hold=true (its attachments are uploaded by now)."""
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    if session.status != "draft":
        raise HTTPException(409, "session is not waiting to start")
    session.status = "queued"
    session.status_source = "native"
    run = create_run(db, session, "initial")
    db.add(AgentEvent(session_id=session.id, run_id=run.id, kind="session.status", source="native", payload={"status": "queued"}))
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/stop", response_model=SessionOut)
def stop_session(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    session.resume_at = None  # stopping also cancels a pending auto-resume
    if session.status not in {"completed", "failed"}:
        session.status = "failed"
        session.status_source = "heartbeat"
        db.add(AgentEvent(session_id=session.id, kind="session.status", source="heartbeat", payload={"status": "failed", "reason": "stopped by user"}))
        notify_users(db, "session", "Session stopped", body="stopped by user", session_id=session.id)
    db.commit()
    return session


# Sessions that no agent process is working on any more; only these may be deleted.
FINISHED_STATUSES = {"completed", "failed", "offline"}


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    # An orchestrator takes its executors with it; files on the worker are left untouched.
    ids, frontier = [session.id], [session.id]
    while frontier:
        frontier = list(db.scalars(select(Session.id).where(Session.parent_session_id.in_(frontier))))
        ids += frontier
    sessions = db.scalars(select(Session).where(Session.id.in_(ids))).all()
    if any(item.status not in FINISHED_STATUSES for item in sessions):
        raise HTTPException(409, "stop the session before deleting it")
    if db.bind.dialect.name == "postgresql":
        # agent_events is append-only; the trigger lets DELETE through only with aihub.purge (0012).
        db.execute(text("SET LOCAL aihub.purge = 'on'"))
    for model in (AgentEvent, Approval, Attachment, Notification, WorkerRequest):
        db.execute(delete(model).where(model.session_id.in_(ids)))
    for item in sessions:
        db.delete(item)
    db.commit()


ACKNOWLEDGEABLE = {"failed", "offline", "blocked"}


@router.post("/{session_id}/acknowledge", response_model=SessionOut)
def acknowledge_session(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    """«Всё ок»: the owner has seen this failure; it stays failed but is no longer shown as a problem."""
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    if session.status not in ACKNOWLEDGEABLE:
        raise HTTPException(409, "only a failed session can be marked as fine")
    session.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/{session_id}/acknowledge", response_model=SessionOut)
def unacknowledge_session(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    session.acknowledged_at = None
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/retry", response_model=SessionOut)
def retry_session(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    original = db.get(Session, session_id)
    if not original:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, original.project_id)
    copy = Session(task_id=original.task_id, project_id=original.project_id, worker_id=original.worker_id,
                   engine=original.engine, provider=original.provider, model=original.model,
                   auth_mode=original.auth_mode, workdir=original.workdir, branch=original.branch,
                   parent_session_id=original.id, account_profile_id=original.account_profile_id,
                   workspace_ref=original.workspace_ref, title=original.title, status="queued",
                   permission_mode=original.permission_mode, mcp_config=original.mcp_config)
    db.add(copy); create_run(db, copy, "retry_after_failure" if original.status == "failed" else "continue"); db.commit(); db.refresh(copy)
    return copy


# --- Claude continuation ---
@router.post("/{session_id}/continue", response_model=SessionOut, status_code=201)
def continue_session(
    session_id: str, data: ContinueIn, user=Depends(write_user), db=Depends(db_dep)
):
    original = db.get(Session, session_id)
    if not original:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, original.project_id)
    # Mock engines take part so the scenario tests can exercise continuation.
    if original.engine not in {"claude_code", "codex"} and not original.engine.startswith("mock"):
        raise HTTPException(409, "продолжение поддерживается только для Claude и Codex")
    if original.status not in {"completed", "failed", "offline"}:
        raise HTTPException(409, "продолжение доступно только для завершённой или упавшей сессии")
    if not original.engine_session_ref:
        raise HTTPException(409, "у сессии нет ссылки на беседу агента — её нельзя продолжить")
    resumed = resume_session(db, original, data.text, data.attachment_ids, model=data.model, fresh=data.fresh,
                             effort=data.effort, permission_mode=data.permission_mode, user=user)
    db.commit()
    db.refresh(resumed)
    return resumed


@router.get("/{session_id}/alternative-accounts")
def alternative_accounts(session_id: str, user=Depends(current_user), db=Depends(db_dep)):
    original = db.get(Session, session_id)
    if not original:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, original.project_id)
    current = db.get(AccountProfile, original.account_profile_id) if original.account_profile_id else None
    if not current:
        return []
    alternatives = db.scalars(select(AccountProfile).where(
        AccountProfile.worker_id == original.worker_id,
        AccountProfile.kind == current.kind,
        AccountProfile.id != current.id,
        AccountProfile.status != "disabled",
    ).order_by(AccountProfile.name)).all()
    return [{
        "account": a,
        "limits": (limits if (limits := account_limits(a, db)).windows else None),
        "resume_mode": CROSS_ACCOUNT_RESUME_MODE,
    } for a in alternatives]


@router.post("/{session_id}/continue-on-account", response_model=SessionOut)
def continue_on_account(session_id: str, data: ContinueOnAccountIn, user=Depends(write_user), db=Depends(db_dep)):
    original = db.get(Session, session_id)
    if not original:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, original.project_id)
    if original.resume_at is None:
        raise HTTPException(409, "session is not waiting for a provider limit")
    target = db.get(AccountProfile, data.account_profile_id)
    current = db.get(AccountProfile, original.account_profile_id) if original.account_profile_id else None
    if not target or not current or target.id == current.id or target.worker_id != original.worker_id or target.kind != current.kind or target.status == "disabled":
        raise HTTPException(409, "alternative account is not compatible")
    recent = db.scalars(select(AgentEvent).where(AgentEvent.session_id == original.id, AgentEvent.kind == "message")
                        .order_by(AgentEvent.cursor.desc()).limit(8)).all()
    summary = "Краткая сводка предыдущей беседы:\n" + "\n".join(
        _safe_resume_summary(str(event.payload.get("text", "")))
        for event in reversed(recent) if event.payload.get("text"))
    resume_text = summary if CROSS_ACCOUNT_RESUME_MODE == "summary" else "Лимит восстановился — продолжай с того места, где остановился."
    resumed = resume_session(db, original, resume_text, user=user, account_profile_id=target.id)
    db.add(AgentEvent(session_id=original.id, kind="session.account_switched", source="native",
                      payload={"from": current.id, "to": target.id, "resume_mode": CROSS_ACCOUNT_RESUME_MODE}))
    db.commit()
    db.refresh(resumed)
    return resumed


@router.post("/{session_id}/events", response_model=list[EventOut])
def post_events(
    session_id: str,
    events: list[EventIn],
    principal=Depends(current_principal),
    db=Depends(db_dep),
):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if isinstance(principal, WorkerToken):
        if principal.worker_id != session.worker_id:
            raise HTTPException(404, "session not found")
    elif not is_admin(principal):
        raise HTTPException(403, "admin role required for write operation")
    # Serialize duplicate checks and run allocation for this session.
    session = db.scalar(select(Session).where(Session.id == session_id).with_for_update().execution_options(populate_existing=True))
    # A tab that lost its event stream still thinks a finished session is running and posts the
    # message here; nobody would read it, so wake the session up the way /continue does.
    user_message = not isinstance(principal, WorkerToken) and any(
        item.kind == "message" and item.payload.get("role") == "user" and (not item.client_event_id or not db.scalar(select(AgentEvent.cursor).where(AgentEvent.session_id == session_id, AgentEvent.client_event_id == item.client_event_id))) for item in events
    )
    if user_message and session.status in FINISHED_STATUSES:
        if session.role not in {"orchestrator", "executor"} or not session.engine_session_ref:
            raise HTTPException(409, "сессия уже завершена — обновите страницу и отправьте сообщение ещё раз")
        trigger = "retry_after_failure" if session.status == "failed" and session.resume_at is None else "continue"
        session.resume_at = None
        run = create_run(db, session, trigger)
        session.status = "queued"
        session.status_source = "native"
        db.add(AgentEvent(session_id=session.id, run_id=run.id, kind="session.status", source="native", payload={"status": "queued", "reason": "продолжение"}))
    out = []
    for item in events:
        if item.client_event_id:
            existing = db.scalar(
                select(AgentEvent).where(
                    AgentEvent.session_id == session_id,
                    AgentEvent.client_event_id == item.client_event_id,
                )
            )
            if existing:
                out.append(existing)
                continue
        payload, changed = redact(item.payload)
        run = latest_run(db, session_id)
        if run and item.client_event_id:
            parts = item.client_event_id.split(":")
            if len(parts) == 3 and parts[0] == session_id and len(parts[1]) <= 64:
                run.external_run_id = parts[1]
        event = AgentEvent(
            run_id=run.id if run else None,
            session_id=session_id,
            client_event_id=item.client_event_id,
            kind=item.kind,
            source=item.source,
            ts=item.ts,
            payload=payload,
            redacted=changed,
        )
        db.add(event)
        db.flush()
        if item.kind == "message" and isinstance(item.payload.get("attachment_ids"), list):
            for attachment_id in item.payload["attachment_ids"][:10]:
                attachment = db.get(Attachment, str(attachment_id))
                if attachment and attachment.session_id == session_id:
                    attachment.sent_at = datetime.now(timezone.utc)
        if item.kind == "approval.request":
            create_from_event(db, session, payload)
        if item.kind == "session.status" and item.payload.get("status"):
            status = item.payload["status"]
            try:
                validate_transition(session.status, status)
            except ValueError as exc:
                if not isinstance(principal, WorkerToken):
                    raise HTTPException(409, str(exc)) from exc
                # A worker's late status (e.g. after the session was stopped) must not cost the whole
                # batch: keep the event as history, leave the session status alone.
                out.append(event)
                continue
            update_run(db, run, status, event.ts, payload)
            session.status = status
            session.status_source = item.source
            _sync_task_status(db, session, status)
            if item.payload.get("engine_session_ref"):
                session.engine_session_ref = str(item.payload["engine_session_ref"])
            if item.payload.get("context_tokens") is not None:
                session.context_tokens = int(item.payload["context_tokens"])
            if status == "failed" and isinstance(principal, WorkerToken):
                schedule_if_limited(db, session)
            if status in {"completed", "failed"}:
                notify_users(db, "session", f"Session {status}", session_id=session.id)
        out.append(event)
    db.commit()
    return out


# --- Permission requests: Claude Code in "ask" mode asks the owner through the hub MCP permission tool ---

def _permit_scope(session_id: str, credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(db_dep)) -> User:
    """The token must carry `permit:<this session id>` (issued to the worker for an "ask" session)."""
    if not credentials:
        raise HTTPException(401, "authentication required")
    try:
        data = jwt.decode(credentials.credentials, Settings().secret_key, algorithms=["HS256"])
    except (jwt.DecodeError, jwt.ExpiredSignatureError, KeyError):
        raise HTTPException(401, "invalid token")
    if f"permit:{session_id}" not in set(str(data.get("scope", "")).split()):
        raise HTTPException(403, "permission scope missing")
    user = db.get(User, data.get("sub"))
    if not user:
        raise HTTPException(401, "invalid token")
    return user


@router.post("/{session_id}/permission-requests", status_code=201)
def request_permission(session_id: str, data: PermissionRequestIn, _user=Depends(_permit_scope), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    details = json.dumps(data.input, ensure_ascii=False, default=str)
    approval = create_from_event(db, session, {
        "action": data.tool_name,
        "summary": redact(details if len(details) <= 2000 else details[:2000] + "…")[0],
        "risk": "high" if data.tool_name in {"Bash", "WebFetch"} or data.tool_name.startswith("mcp__") else "medium",
    })
    if approval is None:
        raise HTTPException(422, "invalid permission request")
    db.flush()
    # The session feed shows it as a card with Allow / Reject.
    db.add(AgentEvent(session_id=session.id, kind="approval.request", source="native", payload={
        "approval_id": approval.id, "action": approval.action, "summary": approval.summary, "risk": approval.risk,
    }))
    db.commit()
    return {"id": approval.id, "status": approval.status}


@router.get("/{session_id}/permission-requests/{approval_id}")
def permission_status(session_id: str, approval_id: str, _user=Depends(_permit_scope), db=Depends(db_dep)):
    approval = db.get(Approval, approval_id)
    if not approval or approval.session_id != session_id:
        raise HTTPException(404, "permission request not found")
    if expire_approval(approval, datetime.now(timezone.utc)):
        db.commit()
    return {"id": approval.id, "status": approval.status}
