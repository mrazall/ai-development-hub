from __future__ import annotations

import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .client import KnowledgeClient

mcp = FastMCP("aihub-knowledge")


def _client() -> KnowledgeClient:
    hub_url = os.environ.get("AIHUB_HUB_URL")
    # The file wins: the worker renews it every few minutes, while the env value was fixed when this
    # server started — after the token lifetime (1 h) it only gave 401 «invalid token» to long orchestrators.
    hub_token = None
    token_file = os.environ.get("AIHUB_HUB_TOKEN_FILE")
    if token_file:
        try:
            with open(token_file, encoding="utf-8") as handle:
                hub_token = handle.read().strip() or None
        except OSError:
            hub_token = None
    hub_token = hub_token or os.environ.get("AIHUB_HUB_TOKEN")
    if hub_url and hub_token:
        return KnowledgeClient(hub_url, hub_token=hub_token, hub_mode=True)
    url = os.environ.get("AIHUB_KNOWLEDGE_URL", "http://127.0.0.1:8001")
    principal = os.environ.get("AIHUB_PRINCIPAL", "")
    if not principal:
        raise RuntimeError("AIHUB_PRINCIPAL is required; knowledge performs authorization")
    return KnowledgeClient(url, principal)


@mcp.tool(name="knowledge.search")
def search(
    query: Annotated[str, Field(min_length=1)],
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
) -> dict:
    with_client = _client()
    try:
        return with_client.search(query, limit)
    finally:
        with_client.close()


@mcp.tool(name="knowledge.read")
def read(document_id: Annotated[str, Field(min_length=1)]) -> dict:
    client = _client()
    try:
        return client.read(document_id)
    finally:
        client.close()


@mcp.tool(name="knowledge.context")
def context(
    query: Annotated[str, Field(min_length=1)],
    limit: Annotated[int, Field(ge=1, le=100)] = 5,
) -> dict:
    client = _client()
    try:
        return client.context(query, limit)
    finally:
        client.close()


@mcp.tool(name="knowledge.decisions")
def decisions(
    query: Annotated[str, Field(min_length=1)] = "decision",
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
) -> dict:
    client = _client()
    try:
        return client.decisions(query, limit)
    finally:
        client.close()


@mcp.tool(name="knowledge.index_status")
def index_status() -> dict:
    client = _client()
    try:
        return client.index_status()
    finally:
        client.close()


@mcp.tool(name="knowledge.handoff.create")
def handoff_create(
    project_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")],
    title: Annotated[str, Field(min_length=1, max_length=200)],
    content: Annotated[str, Field(min_length=1)],
) -> dict:
    client = _client()
    try:
        return client.handoff_create(project_id, title, content)
    finally:
        client.close()


@mcp.tool(name="knowledge.handoff.get")
def handoff_get(document_id: Annotated[str, Field(min_length=1)]) -> dict:
    client = _client()
    try:
        return client.handoff_get(document_id)
    finally:
        client.close()


@mcp.tool(name="knowledge.write_draft")
def write_draft(
    project_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")],
    title: Annotated[str, Field(min_length=1, max_length=200)],
    content: Annotated[str, Field(min_length=1)],
) -> dict:
    client = _client()
    try:
        return client.write_draft(project_id, title, content)
    finally:
        client.close()


@mcp.tool(name="knowledge.propose_update")
def propose_update(
    project_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")],
    title: Annotated[str, Field(min_length=1, max_length=200)],
    content: Annotated[str, Field(min_length=1)],
) -> dict:
    client = _client()
    try:
        return client.propose_update(project_id, title, content)
    finally:
        client.close()


def _orch_session() -> str:
    value = os.environ.get("AIHUB_ORCH_SESSION", "").strip()
    if not value:
        raise RuntimeError("orchestration tools require AIHUB_ORCH_SESSION")
    return value


def orch_spawn_executor(
    title: Annotated[str, Field(min_length=1, max_length=500)],
    prompt: Annotated[str, Field(min_length=1, max_length=200_000)],
    reuse_branch_of: Annotated[str | None, Field(default=None, max_length=36)] = None,
) -> dict:
    client = _client()
    try:
        return client.orch_spawn_executor(_orch_session(), title, prompt, reuse_branch_of)
    finally:
        client.close()


def orch_list_executors() -> list[dict]:
    client = _client()
    try:
        return client.orch_list_executors(_orch_session())
    finally:
        client.close()


def orch_get_executor(executor_id: Annotated[str, Field(min_length=1, max_length=36)]) -> dict:
    client = _client()
    try:
        return client.orch_get_executor(_orch_session(), executor_id)
    finally:
        client.close()


def orch_stop_executor(executor_id: Annotated[str, Field(min_length=1, max_length=36)]) -> dict:
    client = _client()
    try:
        return client.orch_stop_executor(_orch_session(), executor_id)
    finally:
        client.close()


def orch_wait(timeout_s: Annotated[int, Field(ge=0, le=600)] = 600) -> dict:
    """Poll executors every ten seconds until one changes status or timeout."""
    import time
    client = _client()
    try:
        session_id = _orch_session()
        state = lambda item: (item.get("status"), (item.get("merge") or {}).get("state"))  # noqa: E731
        before = {item["id"]: state(item) for item in client.orch_list_executors(session_id)}
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(min(10, max(0, deadline - time.monotonic())))
            current = client.orch_list_executors(session_id)
            if any(state(item) != before.get(item.get("id")) for item in current):
                return {"changed": True, "executors": current}
        return {"changed": False, "executors": client.orch_list_executors(session_id)}
    finally:
        client.close()


def orch_set_plan(
    steps: Annotated[list[dict], Field(max_length=40, description="[{title, status: pending|in_progress|done|blocked, executor_id?}]")],
) -> dict:
    """Publish or update the orchestration plan the owner sees in the panel."""
    client = _client()
    try:
        return client.orch_set_plan(_orch_session(), steps)
    finally:
        client.close()


def orch_request_merge(
    executor_id: Annotated[str, Field(min_length=1, max_length=36)],
    summary: Annotated[str, Field(max_length=4000)] = "",
) -> dict:
    """Manual-merge mode: ask the owner to merge a finished executor branch."""
    client = _client()
    try:
        return client.orch_request_merge(_orch_session(), executor_id, summary)
    finally:
        client.close()


# Every tool description costs context on every turn. Hub chats/orchestrators set AIHUB_MCP_TOOLSET=lean:
# only search, read and draft stay (plus orch_* for orchestrators).
LEAN_TOOLS = {"knowledge.search", "knowledge.read", "knowledge.write_draft"}
if os.environ.get("AIHUB_MCP_TOOLSET", "").strip() == "lean":
    _registry = mcp._tool_manager._tools  # FastMCP keeps registered tools here
    for _name in [name for name in _registry if name not in LEAN_TOOLS]:
        _registry.pop(_name, None)

# Keep the base knowledge server's tool surface minimal. Worker processes set
# AIHUB_ORCH_SESSION for an orchestrator assignment, enabling these tools.
if os.environ.get("AIHUB_ORCH_SESSION", "").strip():
    for _name, _function in {
        "orch_spawn_executor": orch_spawn_executor,
        "orch_list_executors": orch_list_executors,
        "orch_get_executor": orch_get_executor,
        "orch_stop_executor": orch_stop_executor,
        "orch_wait": orch_wait,
        "orch_set_plan": orch_set_plan,
        "orch_request_merge": orch_request_merge,
    }.items():
        mcp.tool(name=_name)(_function)



def permission_request(
    tool_name: Annotated[str, Field(min_length=1, max_length=255)],
    input: dict | None = None,  # noqa: A002 - the name Claude Code passes
    tool_use_id: str | None = None,
) -> str:
    """Claude Code --permission-prompt-tool: ask the owner in the panel and wait for the decision."""
    import json
    import time
    session_id = os.environ.get("AIHUB_PERMISSION_SESSION", "").strip()
    client = _client()
    try:
        request = client.permission_request(session_id, tool_name, input or {})
        status = request.get("status")
        # The approval expires on the hub (default TTL); poll until it is decided or expired.
        while status == "pending":
            time.sleep(3)
            status = client.permission_status(session_id, request["id"]).get("status")
        if status == "approved":
            return json.dumps({"behavior": "allow", "updatedInput": input or {}})
        reason = "the owner rejected this action" if status == "rejected" else "the approval request expired"
        return json.dumps({"behavior": "deny", "message": f"Not allowed: {reason}. Do not retry it; continue without it or stop."})
    finally:
        client.close()


# "Ask" sessions: the worker sets AIHUB_PERMISSION_SESSION, and Claude Code runs with
# --permission-prompt-tool mcp__knowledge__permission_request.
if os.environ.get("AIHUB_PERMISSION_SESSION", "").strip():
    # Claude Code accepts only a single text block from a permission prompt tool: no structured copy.
    mcp.tool(name="permission_request", structured_output=False)(permission_request)

def main() -> None:
    mcp.run()


# Stable Python names for callers embedding the MCP package. The registered
# MCP names above remain compatible with the original direct-mode server.
knowledge_search = search
knowledge_read = read


def knowledge_draft(title: str, content: str) -> dict:
    client = _client()
    try:
        return client.draft(title, content)
    finally:
        client.close()
