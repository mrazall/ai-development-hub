import json

import httpx

from aihub_agents.mcp_config import write_claude_session_config, write_session_config


def test_claude_config_is_written_to_session_workdir_and_keeps_env_reference(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"engine": "claude_code", "config": {"mcpServers": {
            "github": {"command": "docker", "env": {"TOKEN": "${TOKEN}"}}
        }}})

    target = write_session_config(
        tmp_path, "http://hub.test", "project-1", "claude_code", "worker-secret",
        transport=httpx.MockTransport(handler),
    )
    assert target == tmp_path / ".mcp.json"
    assert json.loads(target.read_text())["mcpServers"]["github"]["env"]["TOKEN"] == "${TOKEN}"
    assert seen["authorization"] == "Bearer worker-secret"


def test_codex_config_uses_an_isolated_overlay(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"config": "[mcp_servers.github]\nurl = \"${MCP_URL}\""})

    target = write_session_config(
        tmp_path, "http://hub.test", "project-1", "codex", "worker-secret",
        transport=httpx.MockTransport(handler),
    )
    assert target.name == "config.toml"
    assert target.parent != tmp_path
    assert "${MCP_URL}" in target.read_text()


def test_chat_config_is_private_and_keeps_hub_token_in_env(tmp_path):
    target_dir = tmp_path / "private"
    target = write_claude_session_config(
        target_dir,
        {"append_system_prompt": "search memory first"},
        "https://hub.test",
        "scoped-secret",
        command="/venv/bin/aihub-knowledge-mcp",
    )
    assert target.stat().st_mode & 0o777 == 0o600
    assert target_dir.stat().st_mode & 0o777 == 0o700
    document = json.loads(target.read_text())
    assert document["mcpServers"]["knowledge"]["command"] == "/venv/bin/aihub-knowledge-mcp"
    assert document["mcpServers"]["knowledge"]["env"]["AIHUB_HUB_TOKEN"] == "scoped-secret"
