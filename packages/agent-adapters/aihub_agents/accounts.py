"""Official, non-invasive subscription checks for worker processes.

These functions never read tokens from CLI config files. They only inspect the
documented CLI status/version commands and the existence of the isolated config
directory.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_CREDENTIAL_FILES = {
    "claude_code_subscription": ".credentials.json",
    "codex_subscription": "auth.json",
}


def check_subscription(kind: str, config_dir: str) -> tuple[str, str]:
    path = Path(config_dir).expanduser()
    if not path.is_dir():
        return "pending_login", "isolated config directory does not exist"
    credential_name = _CREDENTIAL_FILES.get(kind)
    if credential_name is None:
        return "error", "unsupported subscription kind"
    # Credential contents are deliberately never opened or inspected. Checking
    # the documented file name distinguishes an unstarted login from a CLI
    # failure without putting tokens in memory or logs.
    if not (path / credential_name).is_file():
        return "pending_login", "official login credentials are not present"
    if kind == "claude_code_subscription":
        command = ["claude", "--version"]
    else:
        command = ["codex", "login", "status"]
    try:
        result = subprocess.run(command, env={**os.environ, "CLAUDE_CONFIG_DIR": str(path), "CODEX_HOME": str(path)}, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "error", "subscription CLI is unavailable"
    if result.returncode == 0:
        return "connected", "official CLI check succeeded"
    return "pending_login", "official CLI reports that login is incomplete"


def list_models(*_args, **_kwargs):
    """Subscriptions do not expose a provider model-list endpoint."""
    return []
