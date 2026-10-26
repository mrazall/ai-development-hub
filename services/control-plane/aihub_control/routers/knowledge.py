from fastapi import APIRouter, Depends, HTTPException, Query
import httpx2 as httpx
from sqlalchemy import select

from ..auth import current_user, db_dep, require_scope, write_user
from ..knowledge import sign_principal
from ..models import AccountProfile, AgentEvent, Project, ProjectMember, Session, Worker
from ..config import Settings
from ..system_settings import get_setting

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/principal")
def knowledge_principal(user=Depends(current_user), db=Depends(db_dep)):
    member_projects = db.scalars(
        select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    )
    shared_projects = db.scalars(select(Project.id).where(Project.visibility.in_(["shared", "public"])))
    project_ids = set(member_projects).union(shared_projects)
    return {"header": sign_principal(user, project_ids)}


def _principal(user, db):
    member_projects = db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
    shared_projects = db.scalars(select(Project.id).where(Project.visibility.in_(["shared", "public"])))
    project_ids = set(member_projects).union(shared_projects)
    project_ids.add(f"personal-{user.username}"[:63])
    return sign_principal(user, project_ids)


def _proxy(path: str, user, db, params=None):
    try:
        response = httpx.get(
            f"{Settings().knowledge_url.rstrip('/')}{path}",
            params=params,
            headers={"X-AIHub-Principal": _principal(user, db)},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "knowledge service unavailable") from exc
    if response.status_code >= 500:
        raise HTTPException(503, "knowledge service unavailable")
    if response.status_code >= 400:
        raise HTTPException(response.status_code, "knowledge request rejected")
    return response.json()


def _proxy_json(path: str, user, db, payload: dict):
    try:
        response = httpx.post(
            f"{Settings().knowledge_url.rstrip('/')}{path}", json=payload,
            headers={"X-AIHub-Principal": _principal(user, db)}, timeout=10,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "knowledge service unavailable") from exc
    if response.status_code >= 500:
        raise HTTPException(503, "knowledge service unavailable")
    if response.status_code >= 400:
        raise HTTPException(response.status_code, "knowledge request rejected")
    return response.json()


@router.get("/search")
def search(q: str = Query(min_length=1), limit: int = Query(20, ge=1, le=100), user=Depends(require_scope("knowledge:read")), db=Depends(db_dep)):
    return _proxy("/search", user, db, {"query": q, "limit": limit})


@router.get("/documents")
def documents(
    sort: str = Query("updated", pattern="^(updated|title)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    project_id: str | None = Query(None),
    type: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(require_scope("knowledge:read")),
    db=Depends(db_dep),
):
    return _proxy(
        "/documents",
        user,
        db,
        {"sort": sort, "order": order, "project_id": project_id, "type": type, "offset": offset, "limit": limit},
    )


@router.get("/documents/{document_id}")
def document(document_id: str, user=Depends(require_scope("knowledge:read")), db=Depends(db_dep)):
    return _proxy(f"/documents/{document_id}", user, db)


@router.post("/drafts", status_code=201)
def draft(payload: dict, user=Depends(require_scope("knowledge:draft")), db=Depends(db_dep)):
    project_id = payload.get("project_id") or f"personal-{user.username}"[:63]
    if not payload.get("title") or not payload.get("content"):
        raise HTTPException(422, "title and content are required")
    return _proxy_json("/drafts", user, db, {
        "project_id": project_id, "title": payload["title"], "content": payload["content"],
        "kind": payload.get("kind", "draft"),
    })


@router.get("/graph")
def graph(user=Depends(current_user), db=Depends(db_dep)):
    return _proxy("/graph", user, db)


@router.get("/health")
def health(user=Depends(current_user), db=Depends(db_dep)):
    return _proxy("/health", user, db)


# --- Agent drafts: review in the hub, applied to the vault by a Claude session ---
VAULT_PROJECT = "knowledge-vault"

APPLY_PROMPT = """Ты — редактор базы знаний Obsidian. Текущая папка — эта база, git-репозиторий.
Внеси в базу черновик агента: файл `_Агенты/{draft_id}`. Его текст ниже.

Правила:
1. Найди заметки, к которым относится содержимое (Glob, Grep, оглавления). Дополняй существующие заметки; новую создавай, только если подходящей нет. Сохраняй язык, стиль и структуру заметок, ставь [[вики-ссылки]].
2. Не удаляй и не переписывай чужой текст без необходимости. Не трогай .obsidian. Секреты (пароли, ключи, токены) в базу не переноси.
3. Перед правкой каждого файла выполни `git status --porcelain -- <файл>`. Если в нём есть незакоммиченные изменения владельца — сначала закоммить только этот файл: `git commit -m "snapshot: правки владельца перед внесением черновика" -- <файл>`.
4. В самом черновике в шапке замени `status: new` на `status: applied`.
5. Закоммить только изменённые и созданные тобой файлы и сам черновик: `git add -- <файлы>` и `git commit -m "knowledge: внесён черновик {title}"`. Никаких push, reset, rebase, checkout.
6. Ответь кратко: какие заметки изменены или созданы, хэш коммита.

Черновик «{title}» (проект {project_id}):

{content}
"""

REVERT_PROMPT = """Текущая папка — база знаний Obsidian, git-репозиторий.
Отмени внесение черновика `_Агенты/{draft_id}`: найди коммит `git log --oneline --grep "внесён черновик"` с названием «{title}» и выполни `git revert --no-edit <хэш>`.
Если revert даёт конфликт — выполни `git revert --abort` и опиши конфликт, ничего больше не меняя.
Затем в черновике в шапке поставь `status: new` и закоммить только этот файл: `git commit -m "knowledge: черновик {title} снова новый" -- <файл>`. Никаких push, reset, rebase, checkout.
Ответь кратко: что откатилось, хэши коммитов."""


def _draft_ref(project_id: str, name: str) -> str:
    return f"draft:{project_id}/{name}"


def _vault_sessions(db, refs: list[str]) -> dict[str, Session]:
    """Latest apply/revert session per draft."""
    rows = db.scalars(select(Session).where(Session.workspace_ref.in_(refs)).order_by(Session.created_at)) if refs else []
    return {row.workspace_ref: row for row in rows}


@router.get("/drafts")
def list_drafts(user=Depends(current_user), db=Depends(db_dep)):
    drafts = _proxy("/drafts", user, db)
    latest = _vault_sessions(db, [_draft_ref(item["project_id"], item["name"]) for item in drafts])
    for item in drafts:
        session = latest.get(_draft_ref(item["project_id"], item["name"]))
        item["session"] = (
            {"id": session.id, "status": session.status, "title": session.title, "project_id": session.project_id}
            if session else None
        )
    return {"items": drafts, "apply_available": bool(get_setting(db, "vault_worker_id") and get_setting(db, "vault_workdir"))}


@router.get("/drafts/{project_id}/{name}")
def get_draft(project_id: str, name: str, user=Depends(current_user), db=Depends(db_dep)):
    return _proxy(f"/drafts/{project_id}/{name}", user, db)


@router.post("/drafts/{project_id}/{name}/dismiss")
def dismiss_draft(project_id: str, name: str, user=Depends(write_user), db=Depends(db_dep)):
    return _proxy_json(f"/drafts/{project_id}/{name}/status", user, db, {"status": "dismissed"})


@router.post("/drafts/{project_id}/{name}/restore")
def restore_draft(project_id: str, name: str, user=Depends(write_user), db=Depends(db_dep)):
    return _proxy_json(f"/drafts/{project_id}/{name}/status", user, db, {"status": "new"})


def _vault_session(db, user, project_id: str, name: str, title: str, prompt: str) -> Session:
    vault_worker_id, vault_workdir = get_setting(db, "vault_worker_id"), get_setting(db, "vault_workdir")
    if not vault_worker_id or not vault_workdir:
        raise HTTPException(409, "внесение в базу не настроено (Настройки → Система: воркер и папка базы)")
    worker = db.get(Worker, vault_worker_id)
    if not worker or worker.status != "online":
        raise HTTPException(409, "worker с базой знаний сейчас не в сети")
    profiles = db.scalars(select(AccountProfile).where(
        AccountProfile.kind == "claude_code_subscription", AccountProfile.worker_id == worker.id,
    ).order_by(AccountProfile.id)).all()
    profile = next(iter(sorted(profiles, key=lambda item: item.status != "ready")), None)
    if not profile:
        raise HTTPException(409, "на worker-е нет профиля Claude")
    ref = _draft_ref(project_id, name)
    running = db.scalar(select(Session).where(
        Session.workspace_ref == ref, Session.status.in_(["queued", "starting", "running"]),
    ))
    if running:
        raise HTTPException(409, "по этому черновику уже идёт сессия")
    project = db.get(Project, VAULT_PROJECT)
    if not project:
        project = Project(id=VAULT_PROJECT, name="База знаний", visibility="private", allowed_paths=[vault_workdir])
        db.add(project)
        db.flush()
    elif vault_workdir not in (project.allowed_paths or []):
        project.allowed_paths = [*(project.allowed_paths or []), vault_workdir]
    session = Session(
        project_id=VAULT_PROJECT, worker_id=worker.id, engine="claude_code", provider="anthropic",
        model=get_setting(db, "vault_model"), auth_mode="subscription", workdir=vault_workdir,
        title=title[:500], account_profile_id=profile.id, role="vault", workspace_ref=ref, status="queued",
    )
    db.add(session)
    db.flush()
    db.add(AgentEvent(session_id=session.id, kind="message", source="native", payload={"role": "user", "text": prompt}))
    db.commit()
    db.refresh(session)
    return session


@router.post("/drafts/{project_id}/{name}/apply", status_code=201)
def apply_draft(project_id: str, name: str, user=Depends(write_user), db=Depends(db_dep)):
    draft = _proxy(f"/drafts/{project_id}/{name}", user, db)
    if draft.get("status") == "applied":
        raise HTTPException(409, "черновик уже внесён")
    prompt = APPLY_PROMPT.format(
        draft_id=draft["id"], title=draft["title"], project_id=project_id, content=draft["content"],
    )
    session = _vault_session(db, user, project_id, name, f"Черновик → база: {draft['title']}", prompt)
    return {"session_id": session.id, "project_id": session.project_id}


@router.post("/drafts/{project_id}/{name}/revert", status_code=201)
def revert_draft(project_id: str, name: str, user=Depends(write_user), db=Depends(db_dep)):
    draft = _proxy(f"/drafts/{project_id}/{name}", user, db)
    if draft.get("status") != "applied":
        raise HTTPException(409, "черновик ещё не внесён")
    prompt = REVERT_PROMPT.format(draft_id=draft["id"], title=draft["title"])
    session = _vault_session(db, user, project_id, name, f"Откат черновика: {draft['title']}", prompt)
    return {"session_id": session.id, "project_id": session.project_id}
