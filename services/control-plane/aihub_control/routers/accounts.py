from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from ..accounts.service import SUBSCRIPTION_KINDS, account_config_dir, secret_fingerprint, write_secret
from ..auth import current_principal, current_user, db_dep, worker_principal, write_user
from ..models import AccountProfile, User, WorkerToken
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


@router.get("", response_model=list[AccountOut])
def list_accounts(worker_id: str | None = Query(default=None), _user=Depends(current_user), db=Depends(db_dep)):
    query = select(AccountProfile).order_by(AccountProfile.name)
    if worker_id:
        query = query.where(AccountProfile.worker_id == worker_id)
    return list(db.scalars(query))


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: str, principal=Depends(current_principal), db=Depends(db_dep)):
    account = _get(db, account_id)
    # --- Worker account access: expose only the assigned profile metadata. ---
    if isinstance(principal, WorkerToken) and principal.worker_id != account.worker_id:
        raise HTTPException(403, "worker token is not authorized for this account")
    if not isinstance(principal, (User, WorkerToken)):
        raise HTTPException(403, "account access denied")
    return account


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountIn, _admin=Depends(write_user), db=Depends(db_dep)):
    _validate_kind(data.kind)
    if db.get(AccountProfile, data.id):
        raise HTTPException(409, "account already exists")
    account = AccountProfile(**data.model_dump(), config_dir=account_config_dir(data.kind, data.id))
    if data.kind in SUBSCRIPTION_KINDS:
        account.status = "pending_login"
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: str, data: AccountPatch, _admin=Depends(write_user), db=Depends(db_dep)):
    account = _get(db, account_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.commit()
    db.refresh(account)
    return account


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
    if account.status != "disabled":
        raise HTTPException(409, "disable account before deletion")
    db.delete(account)
    db.commit()


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

    open_shell = get_setting(db, "worker_shell_hint") or None
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
    return account


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
    return account
