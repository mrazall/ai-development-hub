import httpx

from aihub_agents.adapters import AgentEvent, CodemanAdapter
from aihub_agents.codeman import CodemanClient


def test_create_session_uses_documented_create_and_interactive_calls(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.read()))
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"success": True, "data": {"session": {"id": "sid-1"}}})
        return httpx.Response(200, json={"success": True, "data": {}})

    ref = CodemanClient("http://codeman.test", transport=httpx.MockTransport(handler)).create_session(
        "codex", str(tmp_path), "Night run"
    )
    assert ref == "sid-1"
    assert calls[0][0:2] == ("POST", "/api/v1/sessions")
    assert b'"workingDir"' in calls[0][2]
    assert calls[1][1] == "/api/v1/sessions/sid-1/interactive"


def test_stop_and_sse_events_are_parsed_without_secrets():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            assert request.read() == b'{"input":"\\u001b"}'
            return httpx.Response(200, json={"success": True, "data": {}})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='event: session:working\ndata: {"sessionId":"sid-1"}\n\n'
            'event: terminal:data\ndata: {"text":"done"}\n\n',
        )

    client = CodemanClient("http://codeman.test", password="do-not-log", transport=httpx.MockTransport(handler))
    client.stop_session("sid-1")
    events = list(client.iter_events("sid-1"))
    assert [(event.kind, event.source) for event in events] == [
        ("session:working", "native"),
        ("terminal:data", "cli_parser"),
    ]
    assert events[-1].payload == {"text": "done"}


def test_adapter_uses_client_lifecycle_and_preserves_workspace_ref():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def create_session(self, cli, workdir, title):
            self.calls.append(("create", cli, workdir, title))
            return "codeman-1"

        def iter_events(self, ref):
            yield AgentEvent("terminal:data", {"text": "hello"}, "cli_parser")
            yield AgentEvent("session:completed", {"reason": "done"}, "native")

        def send_input(self, ref, text):
            self.calls.append(("input", ref, text))

        def stop_session(self, ref):
            self.calls.append(("stop", ref))

    async def run():
        fake = FakeClient()
        adapter = CodemanAdapter("http://codeman.test", "workspace-7", "/tmp/project", "Fix it", fake)
        events = [event async for event in adapter.start()]
        await adapter.send("more")
        await adapter.interrupt()
        return fake, events

    fake, events = __import__("asyncio").run(run())
    assert events[0].payload == {
        "status": "running", "external_ref": "codeman-1", "workspace_ref": "workspace-7"
    }
    assert [event.kind for event in events] == ["session.status", "terminal:data", "session.status"]
    assert fake.calls == [("create", "codeman", "/tmp/project", "Fix it"), ("input", "codeman-1", "more"), ("stop", "codeman-1")]


def test_codex_overlay_keeps_base_profile_and_adds_mcp(tmp_path):
    from aihub_agents.worker import _build_codex_overlay

    base, overlay = tmp_path / "base", tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()
    (base / "auth.json").write_text("{}")
    (base / "config.toml").write_text('model = "x"\n')
    _build_codex_overlay(overlay, base, '[mcp_servers.docs]\ncommand = "docs"\n')
    assert (overlay / "auth.json").is_symlink()
    config = (overlay / "config.toml").read_text()
    assert config.startswith('model = "x"') and "[mcp_servers.docs]" in config
    assert (base / "config.toml").read_text() == 'model = "x"\n'
