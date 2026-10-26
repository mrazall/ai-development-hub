from __future__ import annotations

import hashlib
import os
from pathlib import Path


SUBSCRIPTION_KINDS = {"claude_code_subscription", "codex_subscription"}


def secret_fingerprint(value: str) -> str:
    """Stable display-safe fingerprint: first eight digest chars and last four chars."""
    return f"{hashlib.sha256(value.encode()).hexdigest()[:8]}{value[-4:]}"


def account_config_dir(kind: str, account_id: str) -> str | None:
    if kind == "claude_code_subscription":
        return f"~/.aihub/accounts/{account_id}/claude"
    if kind == "codex_subscription":
        return f"~/.aihub/accounts/{account_id}/codex"
    return None


def write_secret(account_id: str, value: str) -> str:
    root = Path(os.environ.get("AIHUB_ACCOUNTS_SECRET_DIR", ".aihub/account-secrets"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = (root / f"{account_id}.key").resolve()
    # Do not follow a pre-existing symlink supplied by an attacker.
    if path.is_symlink():
        raise ValueError("secret path must not be a symlink")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
    except Exception:
        os.close(fd)
        raise
    return str(path)
