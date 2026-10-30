from __future__ import annotations

import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..accounts.service import SUBSCRIPTION_KINDS, account_config_dir, secret_fingerprint, write_secret
from ..auth import current_principal, current_user, db_dep, worker_principal, write_user
from ..models import AccountProfile, Session, User, Worker, WorkerRequest, WorkerToken
from ..orchestration.notifications import notify_users
from ..schemas import ACCOUNT_KINDS, ACCOUNT_STATUSES, AccountIn, AccountOut, AccountPatch, AccountStatusIn, SecretIn

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _validate_kind(kind: str) -> None:
    if kind not in ACCOUNT_KINDS:
        raise HTTPException(422, "unsupported account kind")


def _get(db, account_id: str) -> AccountProfile:
    account = db.get(AccountProfile, account_id)
    if not account:
        raise HTTPException(404, "account not found")
    return account


def _out(db, account: AccountProfile) -> AccountOut:
    result = AccountOut.model_validate(account)
    if account.identity:
        result.duplicate_of = list(db.scalars(select(AccountProfile.id).where(
            AccountProfile.kind == account.kind,
            AccountProfile.identity == account.identity,
            AccountProfile.id != account.id,
        )).all())
    return result


@router.get("/next-id")
def next_account_id(kind: str, _admin=Depends(write_user), db=Depends(db_dep)):
    _validate_kind(kind)
    if kind not in SUBSCRIPTION_KINDS:
        raise HTTPException(422, "next-id is only available for subscription accounts")
    prefix = "claude" if kind == "claude_code_subscription" else "codex"
    used = set(db.scalars(select(AccountProfile.id).where(AccountProfile.id.like(f"{prefix}-%"))).all())
    # Deleted subscription profiles leave an account_delete request behind.  Keep their
    # generated IDs reserved so a late worker request cannot target a newly-created profile.
    used.update(db.scalars(select(WorkerRequest.path).where(
        WorkerRequest.kind == "account_delete",
        WorkerRequest.path.like(f"{prefix}-%"),
    )).all())
    n = 1
    while f"{prefix}-{n}" in used:
        n += 1
    return {"id": f"{prefix}-{n}", "name": f"{prefix.title()} {n}"}


@router.get("/found-logins")
def found_logins(_user=Depends(current_user), db=Depends(db_dep)):
    result = []
    for worker in db.scalars(select(Worker).order_by(Worker.id)):
        for item in worker.found_logins or []:
            engine = item.get("engine")
            result.append({"worker_id": worker.id, "engine": engine, "identity": item.get("identity"),
                           "kind": "claude_code_subscription" if engine == "claude" else "codex_subscription"})
    return result


@router.get("", response_model=list[AccountOut])
def list_accounts(worker_id: str | None = Query(default=None), _user=Depends(current_user), db=Depends(db_dep)):
    query = select(AccountProfile).order_by(AccountProfile.name)
    if worker_id:
        query = query.where(AccountProfile.worker_id == worker_id)
    return [_out(db, account) for account in db.scalars(query)]


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: str, principal=Depends(current_principal), db=Depends(db_dep)):
    account = _get(db, account_id)
    # --- Worker account access: expose only the assigned profile metadata. ---
    if isinstance(principal, WorkerToken) and principal.worker_id != account.worker_id:
        raise HTTPException(403, "worker token is not authorized for this account")
    if not isinstance(principal, (User, WorkerToken)):
        raise HTTPException(403, "account access denied")
    return _out(db, account)


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountIn, _admin=Depends(write_user), db=Depends(db_dep)):
    _validate_kind(data.kind)
    values = data.model_dump(exclude={'adopt_found_login'})
    if data.kind in SUBSCRIPTION_KINDS:
        generated = next_account_id(data.kind, _admin, db) if not data.id or not data.name else None
        if generated:
            values["id"] = values["id"] or generated["id"]
            values["name"] = values["name"] or generated["name"]
        if not values.get("worker_id"):
            workers = list(db.scalars(select(Worker).order_by(Worker.id)))
            online_workers = [worker for worker in workers if worker.status == "online"]
            candidates = online_workers if len(online_workers) == 1 else workers
            if len(candidates) != 1:
                raise HTTPException(422, "worker_id required: several workers")
            values["worker_id"] = candidates[0].id
    if not values.get("id") or not values.get("name") or not values.get("worker_id"):
        raise HTTPException(422, "id, name and worker_id are required")
    if db.get(AccountProfile, values["id"]):
        raise HTTPException(409, "account already exists")
    if data.kind in SUBSCRIPTION_KINDS and db.scalar(select(WorkerRequest.id).where(
        WorkerRequest.kind == "account_delete", WorkerRequest.path == values["id"]
    )):
        raise HTTPException(409, "account id is reserved by a pending or completed delete request")
    account = AccountProfile(**values, config_dir=account_config_dir(data.kind, values["id"]))
    if data.kind in SUBSCRIPTION_KINDS:
        account.status = "pending_login"
    db.add(account)
    if data.adopt_found_login and data.kind in SUBSCRIPTION_KINDS:
        engine = "claude" if data.kind == "claude_code_subscription" else "codex"
        worker = db.get(Worker, account.worker_id)
        found = next((item for item in (worker.found_logins if worker else []) if item.get("engine") == engine), None)
        if not found:
            raise HTTPException(409, "found login is not available")
        account.identity = found.get("identity")
        db.add(WorkerRequest(worker_id=account.worker_id, kind="account_adopt_login", path=account.id,
                             response={"account_id": account.id, "engine": engine}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The next-id response is advisory: another request may create the same ID first.
        # Surface a retryable API conflict instead of leaking a database error as 500.
        if "account_profiles" in str(exc).lower() or "duplicate key" in str(exc).lower():
            raise HTTPException(409, "account id was claimed concurrently; request a new next-id") from exc
        raise
    db.refresh(account)
    return _out(db, account)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: str, data: AccountPatch, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.commit()
    db.refresh(account)
    return _out(db, account)


@router.post("/{account_id}/disable", response_model=AccountOut)
def disable_account(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    account.status = "disabled"
    db.commit()
    db.refresh(account)
    return account


@router.post("/{account_id}/enable", response_model=AccountOut)
def enable_account(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    if account.status == "disabled":
        account.status = "pending_login"
        account.status_detail = "включён; ждём проверку worker-а (до минуты)"
        db.commit()
        db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    active = db.scalar(select(func.count(Session.id)).where(Session.account_profile_id == account.id,
        (Session.status.in_(["queued", "running", "waiting", "waiting_approval"])) | Session.resume_at.is_not(None)))
    if active:
        raise HTTPException(409, "account has active sessions")
    if account.kind in SUBSCRIPTION_KINDS:
        engine = "claude" if account.kind == "claude_code_subscription" else "codex"
        db.add(WorkerRequest(worker_id=account.worker_id, kind="account_delete", path=account.id,
                             response={"account_id": account.id, "engine": engine}))
    db.delete(account)
    db.commit()


def worker_shell_hint(value: str | None, worker_id: str) -> str | None:
    """The command that opens a terminal on *worker_id*: lines `worker=command`, a line without `=` for the rest."""
    fallback = None
    for line in (value or "").splitlines():
        line = line.strip()
        if not line:
            continue
        name, sep, command = line.partition("=")
        if sep and name.strip() and " " not in name.strip():
            if name.strip() == worker_id:
                return command.strip() or None
        else:
            fallback = line
    return fallback


@router.post("/{account_id}/login-instructions")
def login_instructions(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    """Step-by-step login for a subscription profile, run by the owner on the worker's machine."""
    account = _get(db, account_id)
    home = account.config_dir or ""
    parent = home.rsplit("/", 1)[0] if "/" in home else home
    prepare = f"mkdir -p {home} && chmod 700 {parent} {home}"
    # Deployment-specific (e.g. "wsl -d Ubuntu-24.04 -u dev" for a worker in WSL); None hides the step's command.
    from ..config import Settings

    from ..system_settings import get_setting

    # The owner's setting wins; otherwise the worker says how to reach it (WSL distro and user, or ssh).
    from ..models import WorkerCapability

    capability = db.get(WorkerCapability, account.worker_id)
    open_shell = worker_shell_hint(get_setting(db, "worker_shell_hint"), account.worker_id) or (
        capability.shell_hint if capability else None
    )
    if account.kind == "claude_code_subscription":
        steps = [
            {"text": f"На компьютере с worker-ом «{account.worker_id}» откройте терминал, в котором работает worker.", "command": open_shell},
            {"text": "Подготовьте папку профиля (один раз; worker тоже создаёт её сам).", "command": prepare},
            {"text": "Запустите Claude Code с этим профилем.", "command": f"CLAUDE_CONFIG_DIR={home} ~/.local/bin/claude"},
            {"text": "Внутри наберите /login и выберите вход через аккаунт Claude (подписка). Ссылку откройте в браузере, войдите, скопируйте код и вставьте его в терминал.", "command": "/login"},
            {"text": "Когда появится приглашение ко вводу — выйдите. Для второго профиля входите другим аккаунтом Anthropic.", "command": "/exit"},
            {"text": "Вернитесь сюда и нажмите «Проверить соединение» — статус станет «подключён» в течение минуты."},
        ]
        return {"steps": steps, "command": f"CLAUDE_CONFIG_DIR={home} ~/.local/bin/claude"}
    if account.kind == "codex_subscription":
        steps = [
            {"text": f"На компьютере с worker-ом «{account.worker_id}» откройте терминал, в котором работает worker.", "command": open_shell},
            {"text": "Подготовьте папку профиля (один раз; worker тоже создаёт её сам).", "command": prepare},
            {"text": "Запустите вход по коду устройства.", "command": f"CODEX_HOME={home} codex login --device-auth"},
            {"text": "Откройте показанную ссылку в браузере, войдите в аккаунт OpenAI и введите код из терминала. Дождитесь сообщения об успешном входе."},
            {"text": "Вернитесь сюда и нажмите «Проверить соединение» — статус станет «подключён» в течение минуты."},
        ]
        return {"steps": steps, "command": f"CODEX_HOME={home} codex login --device-auth"}
    raise HTTPException(409, "login instructions are only available for subscription accounts")


@router.post("/{account_id}/secret", response_model=AccountOut)
def set_secret(account_id: str, data: SecretIn, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    if account.kind in SUBSCRIPTION_KINDS:
        raise HTTPException(409, "subscription accounts do not accept API secrets")
    path = write_secret(account.id, data.secret)
    account.secret_ref = path
    account.secret_fingerprint = secret_fingerprint(data.secret)
    db.commit()
    db.refresh(account)
    return _out(db, account)


def _models_endpoint(account: AccountProfile) -> tuple[str, dict]:
    defaults = {
        "anthropic_api": "https://api.anthropic.com",
        "openai_api": "https://api.openai.com",
        "gemini_api": "https://generativelanguage.googleapis.com",
        "openrouter": "https://openrouter.ai",
    }
    base = (account.base_url or defaults.get(account.kind, "")).rstrip("/")
    if account.kind == "ollama":
        return urljoin(base + "/", "api/tags"), {}
    if account.kind == "gemini_api":
        return urljoin(base + "/", "v1beta/models"), {}
    if account.kind == "openrouter":
        return urljoin(base + "/", "api/v1/models"), {}
    if account.kind == "openai_compatible":
        return urljoin(base + "/", "models" if base.endswith("/v1") else "v1/models"), {}
    if account.kind == "anthropic_api":
        return urljoin(base + "/", "v1/models"), {"anthropic-version": "2023-06-01"}
    return urljoin(base + "/", "v1/models"), {}


@router.post("/{account_id}/check", response_model=AccountOut)
def check_account(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    previous_status = account.status
    if account.status == "disabled":
        raise HTTPException(409, "account is disabled")
    if account.kind in SUBSCRIPTION_KINDS:
        # Keep the last known status: the worker re-checks the login file within a minute.
        account.status_detail = "проверяем… (worker ответит в течение минуты)"
    else:
        # Ollama needs no key; OpenAI-compatible endpoints may or may not.
        needs_secret = account.kind not in {"ollama", "openai_compatible"}
        if needs_secret and not account.secret_ref:
            account.status, account.status_detail = "error", "secret is not configured"
        else:
            url, extra_headers = _models_endpoint(account)
            headers = dict(extra_headers)
            try:
                secret = Path(account.secret_ref).read_text(encoding="utf-8").strip() if account.secret_ref else None
                # Keys go in headers only — never in the URL, which HTTP client logs may record.
                if secret and account.kind == "gemini_api":
                    headers["x-goog-api-key"] = secret
                elif secret and account.kind == "anthropic_api":
                    headers["x-api-key"] = secret
                elif secret and account.kind != "ollama":  # Ollama has no auth; never send a key there
                    headers["Authorization"] = f"Bearer {secret}"
                params: dict[str, str] = {}
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(url, headers=headers, params=params)
                if response.is_success:
                    account.status, account.status_detail = "connected", None
                    payload = response.json()
                    models = payload.get("models", payload.get("data", [])) if isinstance(payload, dict) else []
                    if isinstance(models, list):
                        discovered = [item.get("name", item.get("id")) for item in models if isinstance(item, dict)]
                        account.models = [str(model) for model in discovered if model]
                else:
                    account.status, account.status_detail = "error", f"provider returned HTTP {response.status_code}"
            except (OSError, httpx.HTTPError, ValueError) as exc:
                account.status, account.status_detail = "error", type(exc).__name__
    account.checked_at = datetime.now(timezone.utc)
    if previous_status != "error" and account.status == "error":
        notify_users(
            db,
            "account.auth_failed",
            "Не удалось проверить аккаунт",
            body=f"Аккаунт {account.id}: {account.status_detail or 'проверка завершилась ошибкой'}",
            severity="warning",
        )
    db.commit()
    db.refresh(account)
    return account


@router.post("/{account_id}/status", response_model=AccountOut)
def worker_status(account_id: str, data: AccountStatusIn, worker=Depends(worker_principal), db=Depends(db_dep)):
    account = _get(db, account_id)
    if not isinstance(worker, WorkerToken) or worker.worker_id != account.worker_id:
        raise HTTPException(403, "worker token is not authorized for this account")
    if account.status == "disabled":
        return account  # an owner's "disabled" is never overridden by a worker report
    if data.status not in ACCOUNT_STATUSES - {"disabled"}:
        raise HTTPException(422, "invalid worker account status")
    if account.kind not in SUBSCRIPTION_KINDS:
        raise HTTPException(409, "worker status is only accepted for subscriptions")
    previous_status = account.status
    account.status, account.status_detail = data.status, data.detail or None
    account.checked_at = datetime.now(timezone.utc)
    if data.identity is not None:
        account.identity = data.identity or None
        account.identity_checked_at = datetime.now(timezone.utc)
    if previous_status != "error" and data.status == "error":
        notify_users(
            db,
            "account.auth_failed",
            "Не удалось авторизовать аккаунт",
            body=f"Аккаунт {account.id}: {data.detail or 'worker сообщил об ошибке авторизации'}",
            severity="warning",
        )
    db.commit()
    db.refresh(account)
    return _out(db, account)


@router.post("/{account_id}/login-started", status_code=202)
def login_started(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    until = datetime.now(timezone.utc) + timedelta(minutes=5)
    account.login_watch_until = until
    db.commit()
    return {"until": until}


@router.get("/{account_id}/login-command")
def login_command(account_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    if account.kind not in SUBSCRIPTION_KINDS:
        raise HTTPException(409, "login command is only available for subscription accounts")
    engine = "claude" if account.kind == "claude_code_subscription" else "codex"
    env_name, command = (("CLAUDE_CONFIG_DIR", "claude auth login") if engine == "claude"
                         else ("CODEX_HOME", "codex login --device-auth"))
    # The line goes into a shell: quote the path, but leave a leading ~/ outside the quotes so it expands.
    path = account.config_dir or ""
    env = f"{env_name}=" + ("~/" + shlex.quote(path[2:]) if path.startswith("~/") else shlex.quote(path))
    return {"engine": engine, "shell": f"{env} {command}", "argv": command.split(),
            "env": {env_name: account.config_dir}, "worker_id": account.worker_id}
