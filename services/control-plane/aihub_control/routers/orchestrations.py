"""Orchestrator-owned API for starting and supervising Codex executors."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from ..auth import db_dep, write_user
from ..config import Settings
from ..deps import project_or_404
from ..models import AccountProfile, AgentEvent, Project, Session, Task, User, Worker
from ..schemas import ExecutorCreateIn, ExecutorDetailOut, ExecutorOut, MergeRequestIn, OrchestrationCreateIn, PlanIn
from ..orchestration.notifications import notify_users

router = APIRouter(prefix="/orchestrations", tags=["orchestrations"])
bearer = HTTPBearer(auto_error=False)


def _profile(db, profile_id: str, kind: str) -> tuple[AccountProfile, Worker]:
    profile = db.get(AccountProfile, profile_id)
    if not profile or profile.kind != kind:
        raise HTTPException(409, f"account profile must be {kind}")
    worker = db.get(Worker, profile.worker_id)
    if not worker or worker.status != "online":
        raise HTTPException(409, f"{kind} account worker is offline")
    return profile, worker


def _scope(
    orchestrator_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db=Depends(db_dep),
) -> User:
    """FastAPI dependency: the token must carry `orchestrate:<the orchestrator id in this URL>`."""
    if not credentials:
        raise HTTPException(401, "authentication required")
    try:
        data = jwt.decode(credentials.credentials, Settings().secret_key, algorithms=["HS256"])
    except (jwt.DecodeError, jwt.ExpiredSignatureError, KeyError):
        raise HTTPException(401, "invalid token")
    scopes = set(str(data.get("scope", "")).split())
    if f"orchestrate:{orchestrator_id}" not in scopes:
        raise HTTPException(403, "orchestrator scope missing")
    user = db.get(User, data.get("sub"))
    if not user:
        raise HTTPException(401, "invalid token")
    return user


PLAN_RULE = (
    "Сразу после чтения ТЗ опубликуй план через mcp__knowledge__orch_set_plan (пункты: что сделать, статус "
    "pending/in_progress/done/blocked, id исполнителя, если пункт ему отдан) и обновляй его при каждом изменении — "
    "владелец видит план в панели. "
)
MANUAL_MERGE_RULE = (
    "Слияние делает владелец: ветки сам НЕ сливай. Когда ветка исполнителя готова и проверена, вызови "
    "mcp__knowledge__orch_request_merge с id исполнителя и кратким описанием (что сделано, что проверено) и жди "
    "решения через mcp__knowledge__orch_wait — у исполнителя появится merge.state merged, conflict или rejected. "
    "При конфликте или отказе запусти доработку с reuse_branch_of. "
)


def _orchestrator_prompt(count: int, manual_merge: bool = False) -> str:
    merge = (
        MANUAL_MERGE_RULE if manual_merge
        else "Готовые ветки сливай в базовую ветку сам (git merge), запускай тесты проекта. "
    )
    return PLAN_RULE + merge + (
        f"Ты — оркестратор. Инструменты оркестрации называются полностью, с префиксом mcp__knowledge__. Разбей ТЗ на независимые задачи и запусти не больше {count} исполнителей одновременно "
        "через mcp__knowledge__orch_spawn_executor. Каждому дай полный самодостаточный промпт: какие файлы, что сделать, критерии "
        "готовности, как проверить. Жди через mcp__knowledge__orch_wait, читай результат через mcp__knowledge__orch_get_executor и смотри изменения "
        "(git diff ветки исполнителя относительно базовой в рабочем каталоге). При недочётах запускай доработку с "
        "reuse_branch_of. Сам работу "
        "исполнителей не делай — только слияние и мелкие правки конфликтов. В конце дай отчёт: что сделано, какие "
        "ветки, что проверено, что осталось. Перед вопросами о проекте ищи ответ в памяти (knowledge). "
        # Claude runs non-interactively: ending the turn ends the run, and background tasks are killed.
        "Ты работаешь без интерактивного режима: конец твоего хода — это конец всей работы. Никогда не жди "
        "фоновыми командами (run_in_background, Monitor) и не заканчивай ход, пока задача не доведена до конца "
        "или не нужен ответ владельца. Исполнители коммитят сами (это делает воркер по их завершении). Если "
        "mcp__knowledge__orch_wait или другой orch_* вернул ошибку — подожди через `sleep 30` в обычной команде Bash и повтори."
    )


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:40] or "executor"


def _executor_payload(db, session: Session) -> dict:
    events = list(db.scalars(select(AgentEvent).where(AgentEvent.session_id == session.id).order_by(AgentEvent.cursor.desc()).limit(50)))
    last_message = next((str((event.payload or {}).get("text", ""))[:2000] for event in events if event.kind == "message" and (event.payload or {}).get("role") == "assistant"), None)
    changed: set[str] = set()
    for event in events:
        values = (event.payload or {}).get("changed_files", [])
        if isinstance(values, list):
            changed.update(str(item) for item in values[:200])
    finished = session.updated_at if session.status in {"completed", "failed", "offline"} else None
    value = ExecutorOut(
        id=session.id, title=session.title, status=session.status, branch=session.branch,
        workdir=session.workdir, last_message=last_message, changed_files=sorted(changed),
        started_at=session.created_at, finished_at=finished, merge=(session.orchestration or {}).get("merge"),
    ).model_dump()
    return value


@router.post("", status_code=201)
def create_orchestration(data: OrchestrationCreateIn, user=Depends(write_user), db=Depends(db_dep)):
    project = project_or_404(db, user, data.project_id)
    orchestrator, orch_worker = _profile(db, data.orchestrator.account_profile_id, "claude_code_subscription")
    executor, executor_worker = _profile(db, data.executors.account_profile_id, "codex_subscription")
    base_workdir = data.workdir or (project.allowed_paths[0] if project.allowed_paths else ".")
    if data.workdir and not any(
        data.workdir == root or data.workdir.startswith(root.rstrip("/") + "/") for root in project.allowed_paths
    ):
        raise HTTPException(422, "workdir must be inside the project's allowed paths")
    base_branch = data.branch or "main"
    task = Task(project_id=project.id, title=data.title, body=data.spec, status="queued")
    db.add(task)
    db.flush()
    session = Session(
        task_id=task.id, project_id=project.id, worker_id=orch_worker.id, engine="claude_code",
        provider="claude", model=data.orchestrator.model or orchestrator.default_model or "claude-opus-5-5",
        auth_mode="subscription", workdir=base_workdir,
        branch=base_branch, title=data.title, role="orchestrator", status="draft" if data.hold else "queued",
        account_profile_id=orchestrator.id,
        orchestration={
            "max_executors": data.executors.count,
            "orchestrator_account_profile_id": orchestrator.id,
            "orchestrator_worker_id": orch_worker.id,
            "orchestrator_model": data.orchestrator.model or orchestrator.default_model or "claude-opus-5-5",
            "executor_account_profile_id": executor.id,
            "executor_model": data.executors.model or executor.default_model or "gpt-5.6-luna",
            "executor_worker_id": executor_worker.id,
            "base_workdir": base_workdir,
            "base_branch": base_branch,
            "manual_merge": data.manual_merge,
            "plan": [],
        },
        mcp_config={"user_id": user.id, "mcpServers": {"knowledge": {"command": "aihub-knowledge-mcp", "args": []}, "orchestration": {"command": "aihub-knowledge-mcp", "args": []}}, "AIHUB_ORCH_SESSION": "pending", "append_system_prompt": _orchestrator_prompt(data.executors.count, data.manual_merge)},
    )
    db.add(session)
    db.flush()
    session.mcp_config = {**(session.mcp_config or {}), "AIHUB_ORCH_SESSION": session.id}
    db.add(AgentEvent(session_id=session.id, kind="message", source="native", payload={"role": "user", "text": data.spec, "attachment_ids": data.attachment_ids}))
    db.commit()
    return {"task_id": task.id, "session_id": session.id, "assignment_id": session.id}


@router.post("/{orchestrator_id}/executors", response_model=ExecutorOut, status_code=201)
def spawn(orchestrator_id: str, data: ExecutorCreateIn, user=Depends(_scope), db=Depends(db_dep)):
    parent = db.get(Session, orchestrator_id)
    if not parent or parent.role != "orchestrator":
        raise HTTPException(404, "orchestration not found")
    config = parent.orchestration or {}
    active = db.scalars(select(Session).where(Session.parent_session_id == parent.id, Session.status.not_in({"completed", "failed", "offline"}))).all()
    if len(active) >= int(config.get("max_executors", 1)):
        raise HTTPException(409, "maximum active executors reached")
    if data.reuse_branch_of:
        source = db.get(Session, data.reuse_branch_of)
        if not source or source.parent_session_id != parent.id:
            raise HTTPException(404, "executor branch not found")
        branch, workdir = source.branch, source.workdir
    else:
        number = len(db.scalars(select(Session).where(Session.parent_session_id == parent.id)).all()) + 1
        branch = f"aihub/{parent.id[:8]}/{number}-{_slug(data.title)}"
        workdir = f"{config.get('base_workdir', '.')}/.aihub/worktrees/{uuid4()}"
    child = Session(task_id=parent.task_id, project_id=parent.project_id, worker_id=config["executor_worker_id"], engine="codex", provider="openai", model=config.get("executor_model", "gpt-5.6-luna"), auth_mode="subscription", workdir=workdir, branch=branch, parent_session_id=parent.id, account_profile_id=config.get("executor_account_profile_id"), title=data.title, role="executor", status="queued", orchestration={"base_workdir": config.get("base_workdir"), "base_branch": config.get("base_branch", "main")}, mcp_config={"user_id": user.id, "AIHUB_ORCH_SESSION": parent.id})
    db.add(child)
    db.flush()
    from ..analytics.runs import create_run, latest_run
    previous = latest_run(db, source.id) if data.reuse_branch_of else None
    create_run(db, child, ("retry_after_failure" if previous and previous.status == "failed" else "rework") if data.reuse_branch_of else "initial")
    db.add(AgentEvent(session_id=child.id, kind="message", source="native", payload={"role": "user", "text": data.prompt}))
    db.commit()
    db.refresh(child)
    return _executor_payload(db, child)


@router.get("/{orchestrator_id}/executors", response_model=list[ExecutorOut])
def list_executors(orchestrator_id: str, _user=Depends(_scope), db=Depends(db_dep)):
    parent = db.get(Session, orchestrator_id)
    if not parent or parent.role != "orchestrator": raise HTTPException(404, "orchestration not found")
    return [_executor_payload(db, item) for item in db.scalars(select(Session).where(Session.parent_session_id == parent.id).order_by(Session.created_at)).all()]


@router.get("/{orchestrator_id}/executors/{session_id}", response_model=ExecutorDetailOut)
def get_executor(orchestrator_id: str, session_id: str, _user=Depends(_scope), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session or session.parent_session_id != orchestrator_id: raise HTTPException(404, "executor not found")
    value = _executor_payload(db, session)
    events = list(db.scalars(select(AgentEvent).where(AgentEvent.session_id == session.id).order_by(AgentEvent.cursor.desc()).limit(50)))
    value["events"] = [{"kind": e.kind, "ts": e.ts, "payload": {k: v for k, v in (e.payload or {}).items() if k in {"role", "text", "status", "changed_files"}}} for e in reversed(events)]
    return value


@router.post("/{orchestrator_id}/executors/{session_id}/stop", response_model=ExecutorOut)
def stop_executor(orchestrator_id: str, session_id: str, _user=Depends(_scope), db=Depends(db_dep)):
    session = db.get(Session, session_id)
    if not session or session.parent_session_id != orchestrator_id: raise HTTPException(404, "executor not found")
    if session.status not in {"completed", "failed", "offline"}: session.status = "failed"
    db.commit()
    db.refresh(session)
    return _executor_payload(db, session)


@router.post("/{orchestrator_id}/plan")
def set_plan(orchestrator_id: str, data: PlanIn, _user=Depends(_scope), db=Depends(db_dep)):
    """The orchestrator publishes (and keeps updating) its plan; the panel shows it."""
    parent = db.get(Session, orchestrator_id)
    if not parent or parent.role != "orchestrator":
        raise HTTPException(404, "orchestration not found")
    plan = [step.model_dump() for step in data.steps]
    parent.orchestration = {**(parent.orchestration or {}), "plan": plan,
                            "plan_updated_at": datetime.now(timezone.utc).isoformat()}
    db.add(AgentEvent(session_id=parent.id, kind="plan", source="native", payload={"steps": plan}))
    db.commit()
    return {"steps": plan}


@router.post("/{orchestrator_id}/executors/{session_id}/merge-request", response_model=ExecutorOut)
def request_merge(orchestrator_id: str, session_id: str, data: MergeRequestIn, _user=Depends(_scope), db=Depends(db_dep)):
    """Manual-merge mode: the orchestrator marks a finished branch as ready; the owner accepts or rejects it."""
    parent = db.get(Session, orchestrator_id)
    child = db.get(Session, session_id)
    if not parent or not child or child.parent_session_id != orchestrator_id:
        raise HTTPException(404, "executor not found")
    if not (parent.orchestration or {}).get("manual_merge"):
        raise HTTPException(409, "this orchestration merges branches itself")
    if child.status != "completed":
        raise HTTPException(409, "executor has not finished")
    if ((child.orchestration or {}).get("merge") or {}).get("state") in {"requested", "merging", "merged"}:
        raise HTTPException(409, "merge already requested")
    child.orchestration = {**(child.orchestration or {}), "merge": {
        "state": "requested", "summary": data.summary, "requested_at": datetime.now(timezone.utc).isoformat(),
    }}
    db.add(AgentEvent(session_id=parent.id, kind="session.status", source="native",
                      payload={"status": parent.status, "reason": f"ждёт слияния: {child.title}"}))
    notify_users(db, "orchestration", f"Ждёт слияния: {child.title}", data.summary[:500], session_id=parent.id)
    db.commit()
    db.refresh(child)
    return _executor_payload(db, child)
