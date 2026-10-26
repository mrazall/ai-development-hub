"""Fetch and install a session-scoped MCP configuration from the Hub."""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

_MAX_CONFIG_BYTES = 256 * 1024


def write_claude_session_config(
    directory: str | os.PathLike[str],
    session_config: dict[str, Any],
    hub_url: str,
    hub_token: str,
    *,
    command: str | None = None,
    token_file: str | os.PathLike[str] | None = None,
    orchestrator_session: str | None = None,
) -> Path:
    """Write the chat-only Hub MCP config with the capability in the child env.

    The token is present only in the MCP server's env section. Claude starts the
    stdio server with this environment, so it never appears in argv, events, or
    the worker worktree after the temporary directory is removed.
    """
    if not hub_url or (not hub_token and not token_file):
        raise ValueError("Hub MCP URL and token are required")
    target_dir = Path(directory)
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The worker's own venv first: a systemd unit's PATH usually does not include it.
    venv_binary = Path(sys.executable).parent / "aihub-knowledge-mcp"
    server_command = command or (str(venv_binary) if venv_binary.is_file() else shutil.which("aihub-knowledge-mcp"))
    if not server_command:
        raise FileNotFoundError("aihub-knowledge-mcp is not installed in the worker environment")
    config = {
        "mcpServers": {
            "knowledge": {
                "command": server_command,
                "args": [],
                "env": {
                    "AIHUB_HUB_URL": hub_url,
                    "AIHUB_HUB_TOKEN": hub_token,
                    **({"AIHUB_HUB_TOKEN_FILE": str(token_file)} if token_file else {}),
                    "AIHUB_MCP_TOOLSET": "lean",  # search/read/draft only — fewer tool descriptions per turn
                    # Registers the orch_* tools (spawn/list/get/wait/stop executors) in mcp-knowledge.
                    **({"AIHUB_ORCH_SESSION": orchestrator_session} if orchestrator_session else {}),
                },
            }
        }
    }
    # The caller supplies the system prompt separately to Claude. Do not copy
    # arbitrary registry entries into a short-lived chat capability config.
    content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if len(content.encode()) > _MAX_CONFIG_BYTES:
        raise ValueError("MCP configuration is too large")
    target = target_dir / "mcp.json"
    target.write_text(content, encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return target


def fetch_config(
    control_plane_url: str,
    project_id: str,
    engine: str,
    worker_token: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch MCP config with a worker token; the token is never persisted."""
    with httpx.Client(base_url=control_plane_url.rstrip("/"), transport=transport, timeout=20.0) as client:
        response = client.get(
            "/api/v0/mcp/config",
            params={"project_id": project_id, "engine": engine},
            headers={"Authorization": f"Bearer {worker_token}"},
        )
        response.raise_for_status()
        body = response.json()
    return body.get("config", body) if isinstance(body, dict) else {}


def write_session_config(
    workdir: str | os.PathLike[str],
    control_plane_url: str,
    project_id: str,
    engine: str,
    worker_token: str,
    *,
    codex_home: str | os.PathLike[str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Write `.mcp.json` for Claude or an isolated Codex `config.toml` overlay."""
    if engine not in {"claude_code", "codex"}:
        raise ValueError("engine must be claude_code or codex")
    config = fetch_config(control_plane_url, project_id, engine, worker_token, transport=transport)
    if engine == "claude_code":
        target = Path(workdir) / ".mcp.json"
        content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    else:
        target_dir = Path(codex_home) if codex_home is not None else Path(
            tempfile.mkdtemp(prefix=".aihub-codex-", dir=str(workdir))
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "config.toml"
        content = str(config)
        if not content.endswith("\n"):
            content += "\n"
    if len(content.encode()) > _MAX_CONFIG_BYTES:
        raise ValueError("MCP configuration is too large")
    target.write_text(content, encoding="utf-8")
    return target


__all__ = ["fetch_config", "write_session_config"]
