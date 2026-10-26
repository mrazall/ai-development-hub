from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx2 as httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from ..auth import current_principal, current_user, db_dep, write_user
from ..models import McpServer, Project, User, WorkerToken
from ..schemas import MCP_TRANSPORTS, McpConfigOut, McpIn, McpOut, McpPatch
from ..deps import project_or_404

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _get(db, server_id: str) -> McpServer:
    server = db.get(McpServer, server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    return server


def _validate(data: McpIn | McpPatch) -> None:
    transport = data.transport
    if transport is not None and transport not in MCP_TRANSPORTS:
        raise HTTPException(422, "unsupported MCP transport")
    if transport == "stdio" and not data.command:
        raise HTTPException(422, "stdio MCP server requires command")
    if transport in {"http", "sse"} and not data.url:
        raise HTTPException(422, f"{transport} MCP server requires url")


def _probe_mcp_server(server: McpServer, client: httpx.Client | None = None) -> tuple[str, str]:
    """Return a redacted registry status; stdio is only checkable on a worker."""
    if server.transport == "stdio":
        return "unknown", "Проверка stdio выполняется на worker-е"
    if not server.url:
        return "error", "URL MCP-сервера не задан"

    owns_client = client is None
    probe_client = client or httpx.Client(timeout=5.0, follow_redirects=False)
    try:
        response = probe_client.head(server.url)
        if response.status_code == 405:
            response = probe_client.get(server.url)
        if response.is_success or 300 <= response.status_code < 400:
            return "ok", f"Доступен (HTTP {response.status_code})"
        return "error", f"Сервер вернул HTTP {response.status_code}"
    except httpx.TimeoutException:
        return "error", "Таймаут проверки (5 с)"
    except httpx.HTTPError:
        return "error", "Не удалось подключиться к MCP-серверу"
    finally:
        if owns_client:
            probe_client.close()


@router.post("/{server_id}/check", response_model=McpOut)
def check_mcp(server_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    server = _get(db, server_id)
    server.status, server.status_detail = _probe_mcp_server(server)
    server.checked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(server)
    return server


@router.get("", response_model=list[McpOut])
def list_mcp(project_id: str | None = Query(default=None), _user=Depends(current_user), db=Depends(db_dep)):
    query = select(McpServer).order_by(McpServer.name)
    servers = list(db.scalars(query))
    if project_id is not None:
        servers = [server for server in servers if project_id in (server.project_ids or [])]
    return servers


@router.get("/config", response_model=McpConfigOut)
def mcp_config(project_id: str, engine: str = Query(...), principal=Depends(current_principal), db=Depends(db_dep)):
    if engine not in {"claude_code", "codex"}:
        raise HTTPException(422, "engine must be claude_code or codex")
    if isinstance(principal, User):
        project = project_or_404(db, principal, project_id)
    elif isinstance(principal, WorkerToken):
        # Worker tokens are the execution-plane capability for session setup.
        # The response contains only enabled registry metadata and env references;
        # it never contains secret values. Project ownership is enforced by the
        # worker/session assignment layer before this endpoint is called.
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "project not found")
    else:
        raise HTTPException(403, "MCP config access denied")
    servers = list(db.scalars(select(McpServer).where(McpServer.enabled.is_(True))))
    selected = [server for server in servers if project_id in (server.project_ids or [])]
    configs = [(server.id, _server_config(server, project.allowed_paths or [])) for server in selected]
    if engine == "claude_code":
        return McpConfigOut(engine=engine, format="json", config={"mcpServers": dict(configs)})
    return McpConfigOut(engine=engine, format="toml", config=_codex_toml(configs))


@router.get("/{server_id}", response_model=McpOut)
def get_mcp(server_id: str, _user=Depends(current_user), db=Depends(db_dep)):
    return _get(db, server_id)


@router.post("", response_model=McpOut, status_code=201)
def create_mcp(data: McpIn, _admin=Depends(write_user), db=Depends(db_dep)):
    _validate(data)
    if db.get(McpServer, data.id):
        raise HTTPException(409, "MCP server already exists")
    if data.project_ids:
        missing = [project_id for project_id in data.project_ids if not db.get(Project, project_id)]
        if missing:
            raise HTTPException(404, f"project not found: {missing[0]}")
    server = McpServer(**data.model_dump())
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


@router.patch("/{server_id}", response_model=McpOut)
def update_mcp(server_id: str, data: McpPatch, _admin=Depends(write_user), db=Depends(db_dep)):
    server = _get(db, server_id)
    values = data.model_dump(exclude_unset=True)
    transport = values.get("transport", server.transport)
    command = values.get("command", server.command)
    url = values.get("url", server.url)
    if transport not in MCP_TRANSPORTS:
        raise HTTPException(422, "unsupported MCP transport")
    if transport == "stdio" and not command:
        raise HTTPException(422, "stdio MCP server requires command")
    if transport in {"http", "sse"} and not url:
        raise HTTPException(422, f"{transport} MCP server requires url")
    if "project_ids" in values:
        missing = [project_id for project_id in values["project_ids"] if not db.get(Project, project_id)]
        if missing:
            raise HTTPException(404, f"project not found: {missing[0]}")
    for key, value in values.items():
        setattr(server, key, value)
    db.commit()
    db.refresh(server)
    return server


@router.post("/{server_id}/enable", response_model=McpOut)
def enable_mcp(server_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    server = _get(db, server_id)
    server.enabled = True
    db.commit()
    db.refresh(server)
    return server


@router.post("/{server_id}/disable", response_model=McpOut)
def disable_mcp(server_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    server = _get(db, server_id)
    server.enabled = False
    db.commit()
    db.refresh(server)
    return server


@router.put("/{server_id}/projects/{project_id}", response_model=McpOut)
def assign_mcp(server_id: str, project_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    server = _get(db, server_id)
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    if project_id not in (server.project_ids or []):
        server.project_ids = [*server.project_ids, project_id]
        db.commit()
        db.refresh(server)
    return server


@router.delete("/{server_id}/projects/{project_id}", response_model=McpOut)
def unassign_mcp(server_id: str, project_id: str, _admin=Depends(write_user), db=Depends(db_dep)):
    server = _get(db, server_id)
    server.project_ids = [item for item in (server.project_ids or []) if item != project_id]
    db.commit()
    db.refresh(server)
    return server


def _env_for(server: McpServer) -> dict[str, str]:
    env: dict[str, str] = {}
    if server.id == "github":
        env["GITHUB_TOKEN"] = "${GITHUB_TOKEN}"
    return env


def _server_config(server: McpServer, allowed_paths: list[str]) -> dict[str, Any]:
    if server.id == "filesystem":
        command = list(server.command)
        # Registry metadata cannot grant paths; project allowlist is authoritative.
        command = command[:1] + list(allowed_paths)
    else:
        command = list(server.command)
    if server.transport in {"http", "sse"}:
        return {"type": server.transport, "url": server.url}
    result: dict[str, Any] = {"command": command[0], "args": command[1:]}
    env = _env_for(server)
    if env:
        result["env"] = env
    return result


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _codex_toml(servers: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for server_id, config in servers:
        lines.append(f"[mcp_servers.{server_id}]")
        if config.get("type") == "http":
            lines.append(f"url = {_toml_string(config['url'])}")
        else:
            lines.append(f"command = {_toml_string(config['command'])}")
            args = ", ".join(_toml_string(item) for item in config.get("args", []))
            lines.append(f"args = [{args}]")
            for key, value in config.get("env", {}).items():
                lines.append(f"[mcp_servers.{server_id}.env]")
                lines.append(f"{key} = {_toml_string(value)}")
        lines.append("")
    return "\n".join(lines)
