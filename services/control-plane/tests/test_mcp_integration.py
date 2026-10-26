from test_api_integration import admin_token as mcp_admin
from test_api_integration import auth, client as mcp_client
from test_api_integration import clean_schema as clean_schema_fixture
from test_api_integration import make_project

import pytest

pytestmark = pytest.mark.integration


def _server_payload(server_id="custom-filesystem"):
    return {
        "id": server_id,
        "name": "Filesystem",
        "source": "https://example.test/mcp",
        "version": "1.0.0",
        "license": "MIT",
        "transport": "stdio",
        "command": ["npx", "filesystem"],
        "scopes": ["fs:read"],
        "tools": ["read_file"],
    }


def test_mcp_crud_assignment_rbac_and_config(mcp_client, mcp_admin, clean_schema_fixture):  # noqa: F811
    project = make_project(mcp_client, mcp_admin, "mcp-project")
    headers = auth(mcp_admin)
    created = mcp_client.post("/api/v0/mcp", headers=headers, json=_server_payload())
    assert created.status_code == 201
    assert created.json()["enabled"] is False
    assert mcp_client.put(f"/api/v0/mcp/custom-filesystem/projects/{project['id']}", headers=headers).status_code == 200
    assert mcp_client.post("/api/v0/mcp/custom-filesystem/enable", headers=headers).json()["enabled"] is True

    response = mcp_client.get(
        "/api/v0/mcp/config", headers=headers, params={"project_id": project["id"], "engine": "claude_code"}
    )
    assert response.status_code == 200
    config = response.json()["config"]["mcpServers"]["custom-filesystem"]
    assert config["args"] == ["filesystem"]

    mcp_client.patch(
        f"/api/v0/projects/{project['id']}",
        headers=headers,
        json={"id": project["id"], "name": project["id"], "allowed_paths": ["/safe/project"]},
    )
    config = mcp_client.get(
        "/api/v0/mcp/config", headers=headers, params={"project_id": project["id"], "engine": "claude_code"}
    ).json()["config"]["mcpServers"]["custom-filesystem"]
    assert config["args"] == ["filesystem"]


def test_mcp_config_only_enabled_assigned_servers(mcp_client, mcp_admin, clean_schema_fixture):  # noqa: F811
    project = make_project(mcp_client, mcp_admin, "mcp-private")
    headers = auth(mcp_admin)
    mcp_client.post("/api/v0/mcp", headers=headers, json=_server_payload("unassigned"))
    response = mcp_client.get(
        "/api/v0/mcp/config", headers=headers, params={"project_id": project["id"], "engine": "codex"}
    )
    assert response.status_code == 200
    assert "unassigned" not in response.json()["config"]


def test_mcp_check_records_stdio_unknown_and_time(mcp_client, mcp_admin, clean_schema_fixture):  # noqa: F811
    headers = auth(mcp_admin)
    created = mcp_client.post(
        "/api/v0/mcp", headers=headers, json=_server_payload("check-stdio")
    )
    assert created.status_code == 201
    checked = mcp_client.post("/api/v0/mcp/check-stdio/check", headers=headers)
    assert checked.status_code == 200
    body = checked.json()
    assert body["status"] == "unknown"
    assert body["status_detail"] == "Проверка stdio выполняется на worker-е"
    assert body["checked_at"]
