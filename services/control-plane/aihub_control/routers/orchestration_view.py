"""The owner's view of an orchestration: plan, executors with usage and limits, manual merge decisions."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth import current_user, db_dep, write_user
from ..deps import project_or_404
from ..models import AccountLimit, AccountProfile, AgentEvent, Session, WorkerRequest
from ..orchestration.auto_resume import resume_session
from ..schemas import MergeDecisionIn
from .orchestrations import _executor_payload

router = APIRouter(prefix="/sessions", tags=["orchestrations"])

FINISHED = {"completed", "failed", "offline"}


def usage_of(db, session_id: str) -> dict:
    """Tokens and API-equivalent cost reported by the engine: Claude per run (`result`), Codex per turn."""
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "cost_usd": None}
    rows = db.scalars(select(AgentEvent).where(AgentEvent.session_id == session_id, AgentEvent.kind.in_(["message", "output"])))
    for event in rows:
        payload = event.payload or {}
        if payload.get("raw_type") not in {"result", "turn.completed"}:
            continue
        usage = payload.get("usage") or {}
        total["input_tokens"] += int(usage.get("input_tokens") or 0)
        total["cached_input_tokens"] += int(usage.get("cached_input_tokens") or usage.get("cache_read_input_tokens") or 0)
        total["output_tokens"] += int(usage.get("output_tokens") or 0)
        if isinstance(payload.get("cost_usd"), (int, float)):
            total["cost_usd"] = round((total["cost_usd"] or 0) + float(payload["cost_usd"]), 4)
    return total


def _account(db, account_id: str | None) -> dict | None:
    if not account_id:
        return None
    profile = db.get(AccountProfile, account_id)
    windows = db.scalars(select(AccountLimit).where(AccountLimit.account_id == account_id)).all()
    return {
        "id": account_id,
        "name": profile.name if profile else account_id,
        "windows": [{"kind": row.kind, "used_percent": row.used_percent, "resets_at": row.resets_at} for row in windows],
    }


def _orchestrator(db, user, session_id: str) -> Session:
    session = db.get(Session, session_id)
    if not session or session.role != "orchestrator":
        raise HTTPException(404, "orchestration not found")
    project_or_404(db, user, session.project_id)
    return session


@router.get("/{session_id}/orchestration")
def orchestration_view(session_id: str, user=Depends(current_user), db=Depends(db_dep)):
    parent = _orchestrator(db, user, session_id)
    config = parent.orchestration or {}
    children = db.scalars(select(Session).where(Session.parent_session_id == parent.id).order_by(Session.created_at)).all()
    executors = []
    for child in children:
        item = _executor_payload(db, child)
        item["usage"] = usage_of(db, child.id)
        item["account"] = _account(db, child.account_profile_id)
        executors.append(item)
    return {
        "plan": config.get("plan") or [],
        "plan_updated_at": config.get("plan_updated_at"),
        "manual_merge": bool(config.get("manual_merge")),
        "max_executors": config.get("max_executors"),
        "base_branch": config.get("base_branch"),
        "orchestrator": {"usage": usage_of(db, parent.id), "account": _account(db, parent.account_profile_id)},
        "executors": executors,
    }


def _executor(db, user, session_id: str) -> tuple[Session, Session]:
    child = db.get(Session, session_id)
    if not child or child.role != "executor" or not child.parent_session_id:
        raise HTTPException(404, "executor not found")
    parent = _orchestrator(db, user, child.parent_session_id)
    return child, parent


def _set_merge(child: Session, **values) -> None:
    merge = {**((child.orchestration or {}).get("merge") or {}), **values}
    child.orchestration = {**(child.orchestration or {}), "merge": merge}


def tell_orchestrator(db, parent: Session, text: str) -> None:
    """The decision reaches the orchestrator as a message; a finished orchestrator is woken up by it."""
    if parent.status in FINISHED and parent.engine_session_ref:
        resume_session(db, parent, text)
    else:
        db.add(AgentEvent(session_id=parent.id, kind="message", source="native", payload={"role": "user", "text": text}))


@router.post("/{session_id}/merge/accept")
def accept_merge(session_id: str, user=Depends(write_user), db=Depends(db_dep)):
    child, parent = _executor(db, user, session_id)
    if ((child.orchestration or {}).get("merge") or {}).get("state") not in {"requested", "conflict"}:
        raise HTTPException(409, "merge was not requested")
    config = parent.orchestration or {}
    # The worker that holds the orchestration checkout merges there (base branch, clean tree, abort on conflict).
    db.add(WorkerRequest(worker_id=parent.worker_id, session_id=parent.id, kind="git_merge", path=child.branch,
                         response={"base_branch": config.get("base_branch", "main"), "executor_id": child.id}))
    _set_merge(child, state="merging", decided_at=datetime.now(timezone.utc).isoformat(), decided_by=user.username)
    db.commit()
    return _executor_payload(db, child)


@router.post("/{session_id}/merge/reject")
def reject_merge(session_id: str, data: MergeDecisionIn, user=Depends(write_user), db=Depends(db_dep)):
    child, parent = _executor(db, user, session_id)
    if ((child.orchestration or {}).get("merge") or {}).get("state") not in {"requested", "conflict"}:
        raise HTTPException(409, "merge was not requested")
    _set_merge(child, state="rejected", reason=data.reason, decided_at=datetime.now(timezone.utc).isoformat(),
               decided_by=user.username)
    tell_orchestrator(db, parent, f"Владелец отклонил слияние ветки {child.branch} ({child.title})."
                      + (f" Причина: {data.reason}" if data.reason else "") + " Доработай через reuse_branch_of.")
    db.commit()
    return _executor_payload(db, child)


def finish_merge(db, request: WorkerRequest, payload: dict) -> None:
    """Called when the worker answers a git_merge request."""
    params = request.response if isinstance(request.response, dict) else {}
    child = db.get(Session, str(params.get("executor_id") or ""))
    parent = db.get(Session, request.session_id) if request.session_id else None
    if not child or not parent:
        return
    error = payload.get("error")
    if error:
        _set_merge(child, state="conflict", error=str(error)[:500])
        tell_orchestrator(db, parent, f"Слияние ветки {child.branch} не удалось: {error}. Разреши конфликт доработкой "
                                      "исполнителя (reuse_branch_of) и снова запроси слияние.")
    else:
        result = payload.get("result") or {}
        _set_merge(child, state="merged", head=result.get("head"))
        tell_orchestrator(db, parent, f"Владелец принял слияние: ветка {child.branch} влита в "
                                      f"{result.get('into', 'базовую')} ({result.get('head', '')}). Продолжай по плану.")
