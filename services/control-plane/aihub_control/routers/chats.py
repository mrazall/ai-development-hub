"""Personal Claude chat chains exposed to the web workspace."""

import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from ..auth import current_user, db_dep, write_user
from ..config import Settings
from ..system_settings import get_setting
from ..models import AccountProfile, AgentEvent, Project, Session, Worker
from ..schemas import ChatCreateIn, ChatMessageOut, ChatOut, ChatPatchIn

router = APIRouter(prefix="/chats", tags=["chats"])

_PROMPT = (
    "Ты — личный помощник пользователя. Для вопросов о его инфраструктуре и проектах "
    "сначала ищи в памяти (инструмент knowledge). Сохраняй в память только по явной просьбе — как черновик."
)


def _title(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()[:60]


def _personal_project(db, user) -> Project:
    project_id = f"personal-{user.username}"[:63]
    project = db.get(Project, project_id)
    if not project:
        project = Project(
            id=project_id,
            name="Личные чаты",
            visibility="private",
            is_personal=True,
            allowed_paths=["~/.aihub/chats/"],
        )
        db.add(project)
        db.flush()
        db.commit()
        db.refresh(project)
    return project


def _worker_and_profile(db, user, account_id: str | None):
    profile = db.get(AccountProfile, account_id) if account_id else None
    if account_id and (not profile or profile.kind != "claude_code_subscription"):
        raise HTTPException(409, "профиль Claude не найден")
    if profile:
        worker = db.get(Worker, profile.worker_id)
        if not worker or worker.status != "online":
            raise HTTPException(409, "worker профиля Claude недоступен")
        return worker, profile
    # No profile given: use a Claude subscription profile on an online worker (ready ones first). Running
    # without a profile would use the worker's default Claude home, which is usually not logged in.
    candidates = db.scalars(
        select(AccountProfile).where(AccountProfile.kind == "claude_code_subscription").order_by(AccountProfile.id)
    ).all()
    for profile in sorted(candidates, key=lambda item: item.status != "ready"):
        worker = db.get(Worker, profile.worker_id)
        if worker and worker.status == "online":
            return worker, profile
    raise HTTPException(409, "нет профиля Claude на доступном worker-е")


def _mcp_config(db=None) -> dict:
    return {
        "mcpServers": {
            "knowledge": {
                "command": "aihub-knowledge-mcp",
                "args": [],
                "cwd": "packages/mcp-knowledge",
            }
        },
        "append_system_prompt": get_setting(db, "chat_system_prompt") or _PROMPT,
    }


def _mcp_config_for(user, db=None) -> dict:
    config = _mcp_config(db)
    # The user id is an ACL subject, not a credential. The assignment endpoint
    # exchanges it for a short-lived scoped token on the worker's behalf.
    config["user_id"] = user.id
    return config


def _sessions_for_chat(db, root: Session) -> list[Session]:
    rows = list(db.scalars(select(Session).where(Session.chat_id == root.id)))
    # Be tolerant of old continuation records created before chat_id existed.
    known = {row.id for row in rows}
    frontier = [root.id]
    while frontier:
        children = list(db.scalars(select(Session).where(Session.parent_session_id.in_(frontier))))
        frontier = [child.id for child in children if child.id not in known]
        rows.extend(child for child in children if child.id not in known)
        known.update(frontier)
    return sorted(rows, key=lambda row: (row.created_at, row.id))


def _message_rows(db, root: Session) -> list[ChatMessageOut]:
    sessions = _sessions_for_chat(db, root)
    ids = [session.id for session in sessions]
    if not ids:
        return []
    events = db.scalars(
        select(AgentEvent).where(AgentEvent.session_id.in_(ids)).order_by(AgentEvent.cursor)
    )
    result = []
    for event in events:
        payload = event.payload or {}
        if event.kind == "message":
            if payload.get("partial") or payload.get("role") not in {"user", "assistant"}:
                continue
            # Claude's final `result` repeats the last answer; empty texts are tool-only turns.
            if payload.get("raw_type") == "result" or not str(payload.get("text", "")).strip():
                continue
            result.append(ChatMessageOut(
                id=str(event.cursor), role=payload["role"], text=str(payload.get("text", "")),
                created_at=event.ts,
            ))
        elif event.kind in {"tool.call", "tool.result"}:
            name = payload.get("tool_name") or payload.get("name") or "tool"
            if event.kind == "tool.result":
                continue  # the call row is enough in a chat; full output stays in the session view
            summary = payload.get("tool_summary") or payload.get("summary") or payload.get("text") or ""
            result.append(ChatMessageOut(
                id=str(event.cursor), role="tool", text=str(summary)[:160], tool_name=str(name),
                tool_summary=str(summary)[:160], created_at=event.ts,
            ))
    return result


def _chat(db, root: Session, with_messages: bool = False) -> dict:
    messages = _message_rows(db, root)
    latest = max(_sessions_for_chat(db, root), key=lambda row: (row.updated_at, row.id))
    first = next((message.text for message in messages if message.role == "user"), None)
    value = {
        "id": root.id, "title": root.title or _title(first or "Новый чат"),
        "pinned": root.pinned, "archived": root.archived, "session_id": latest.id,
        "model": latest.model, "account_profile_id": latest.account_profile_id,
        "effort": (latest.mcp_config or {}).get("effort"),
        "updated_at": latest.updated_at, "created_at": root.created_at,
        "first_message": first, "status": latest.status,
        "context": {"used": latest.context_tokens or 0, "limit": Settings().claude_context_limit},
    }
    if with_messages:
        value["messages"] = messages
    return value


def _roots(db, user):
    project = _personal_project(db, user)
    return project, list(db.scalars(
        select(Session).where(
            Session.project_id == project.id, Session.parent_session_id.is_(None),
            Session.chat_id.is_not(None), Session.archived.is_(False),
        ).order_by(Session.pinned.desc(), Session.updated_at.desc())
    ))


@router.get("", response_model=list[ChatOut])
def list_chats(q: str | None = Query(None, max_length=200), user=Depends(current_user), db=Depends(db_dep)):
    _, roots = _roots(db, user)
    if q:
        needle = q.casefold()
        roots = [root for root in roots if needle in (root.title or "").casefold() or needle in " ".join(
            message.text for message in _message_rows(db, root) if message.role == "user"
        ).casefold()]
    return [_chat(db, root) for root in roots]


@router.get("/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: str, user=Depends(current_user), db=Depends(db_dep)):
    project, _ = _roots(db, user)
    root = db.scalar(select(Session).where(Session.id == chat_id, Session.project_id == project.id))
    if not root or root.archived:
        raise HTTPException(404, "chat not found")
    return _chat(db, root, with_messages=True)


@router.post("", response_model=ChatOut, status_code=201)
def create_chat(data: ChatCreateIn, user=Depends(write_user), db=Depends(db_dep)):
    project = _personal_project(db, user)
    worker, profile = _worker_and_profile(db, user, data.account_profile_id)
    model = data.model or (profile.default_model if profile else None) or "claude-opus-5-5"
    session = Session(
        project_id=project.id, worker_id=worker.id, engine=get_setting(db, "chat_engine"), provider="anthropic",
        model=model, auth_mode="subscription", workdir="~/.aihub/chats/", title=_title(data.text),
        account_profile_id=profile.id if profile else None, status="queued",
        mcp_config={**_mcp_config_for(user, db), **({"effort": data.effort} if data.effort else {})},
    )
    db.add(session)
    db.flush()
    session.chat_id = session.id
    session.workdir = f"~/.aihub/chats/{session.id}"
    db.add(AgentEvent(session_id=session.id, kind="message", source="native", payload={
        "role": "user", "text": data.text, "attachment_ids": data.attachment_ids,
    }))
    db.commit()
    db.refresh(session)
    return _chat(db, session)


@router.patch("/{chat_id}", response_model=ChatOut)
def patch_chat(chat_id: str, data: ChatPatchIn, user=Depends(write_user), db=Depends(db_dep)):
    project, _ = _roots(db, user)
    root = db.scalar(select(Session).where(Session.id == chat_id, Session.project_id == project.id))
    if not root or root.archived:
        raise HTTPException(404, "chat not found")
    values = data.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(root, key, value)
    db.commit()
    db.refresh(root)
    return _chat(db, root)


@router.delete("/{chat_id}", response_model=ChatOut)
def archive_chat(chat_id: str, user=Depends(write_user), db=Depends(db_dep)):
    project, _ = _roots(db, user)
    root = db.scalar(select(Session).where(Session.id == chat_id, Session.project_id == project.id))
    if not root:
        raise HTTPException(404, "chat not found")
    root.archived = True
    db.commit()
    db.refresh(root)
    return _chat(db, root)
