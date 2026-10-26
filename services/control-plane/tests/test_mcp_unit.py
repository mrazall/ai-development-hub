from types import SimpleNamespace

import httpx2 as httpx

from aihub_control.routers.mcp import _codex_toml, _probe_mcp_server, _server_config


def test_filesystem_config_uses_only_project_allowlist():
    server = SimpleNamespace(id="filesystem", transport="stdio", command=["npx", "filesystem", "/unsafe"])
    config = _server_config(server, ["/workspace/project"])
    assert config["args"] == ["/workspace/project"]
    assert "/unsafe" not in config["args"]


def test_github_token_is_environment_reference():
    server = SimpleNamespace(id="github", transport="stdio", command=["docker", "run"])
    config = _server_config(server, [])
    assert config["env"] == {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}


def test_codex_config_is_toml_fragment_without_secret_values():
    fragment = _codex_toml([("github", {"command": "docker", "args": [], "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}})])
    assert "[mcp_servers.github]" in fragment
    assert 'GITHUB_TOKEN = "${GITHUB_TOKEN}"' in fragment
    assert "secret" not in fragment.lower()


def test_http_check_uses_get_when_head_is_not_supported():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(405 if request.method == "HEAD" else 200, request=request)

    server = SimpleNamespace(transport="http", url="https://mcp.example.test/sse")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status, detail = _probe_mcp_server(server, client)
    assert (status, detail) == ("ok", "Доступен (HTTP 200)")
    assert requests == ["HEAD", "GET"]


def test_http_check_does_not_store_response_body_or_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"X-Secret": "do-not-store"}, text="token=secret")

    server = SimpleNamespace(transport="http", url="https://mcp.example.test")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status, detail = _probe_mcp_server(server, client)
    assert status == "error"
    assert detail == "Сервер вернул HTTP 503"
    assert "secret" not in detail.lower()


def test_stdio_check_is_unknown_and_does_not_start_a_process():
    server = SimpleNamespace(transport="stdio", url=None)
    assert _probe_mcp_server(server) == ("unknown", "Проверка stdio выполняется на worker-е")
