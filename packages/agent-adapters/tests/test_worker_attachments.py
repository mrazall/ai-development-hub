import asyncio

from aihub_agents.adapters import MockAdapter
from aihub_agents.worker import Worker


class Response:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def test_worker_downloads_metadata_named_attachment_into_session_dir(tmp_path):
    worker = Worker("http://control", "worker-a", "token")
    calls = []

    async def request(_client, method, path, **_kwargs):
        calls.append(path)
        if path.endswith("/attachments"):
            return Response(payload=[{
                "id": "att-1",
                "original_name": "фото;draft.png",
                "mime_type": "image/png",
                "size_bytes": 8,
            }])
        return Response(content=b"png data")

    events = []

    async def post_event(*args):
        events.append(args[-1])

    worker._request = request
    worker._post_event = post_event
    links = asyncio.run(worker._download_attachments(
        object(), {"id": "session-1"}, "assignment-1", None, tmp_path
    ))

    target = tmp_path / ".aihub" / "attachments" / "session-1" / "фото_draft.png"
    assert target.read_bytes() == b"png data"
    assert links == [".aihub/attachments/session-1/фото_draft.png (image/png, 8 bytes)"]
    assert calls == [
        "/api/v0/assignments/session-1/attachments",
        "/api/v0/assignments/session-1/attachments/att-1",
    ]
    assert events == []


def test_worker_reports_unavailable_attachment_and_accepts_non_git_workdir(tmp_path):
    worker = Worker("http://control", "worker-a", "token")

    async def request(_client, method, path, **_kwargs):
        if path.endswith("/attachments"):
            return Response(payload=[{
                "id": "missing",
                "original_name": "notes.txt",
                "mime_type": "text/plain",
                "size_bytes": 4,
            }])
        return Response(status_code=404)

    events = []

    async def post_event(*args):
        events.append(args[-1])

    worker._request = request
    worker._post_event = post_event
    assert asyncio.run(worker._download_attachments(
        object(), {"id": "session-2"}, "assignment-2", ["missing"], tmp_path
    )) == []
    assert events[0]["kind"] == "output"
    assert events[0]["payload"]["stream"] == "stderr"
    assert "missing" in events[0]["payload"]["text"]
    assert not (tmp_path / ".git").exists()


def test_mock_echo_prompt_exposes_attachment_paths():
    async def collect():
        adapter = MockAdapter("echo_prompt", "Пользователь приложил файлы: .aihub/attachments/s-1/note.md")
        return [event async for event in adapter.start()]

    events = asyncio.run(collect())
    assert events[1].kind == "message"
    assert ".aihub/attachments/s-1/note.md" in events[1].payload["text"]


def test_worker_reports_subscription_file_presence_without_reading_contents(tmp_path, monkeypatch):
    # Hermetic: the real `claude`/`codex` may or may not be installed where the tests run. Here the CLI is
    # unavailable, so only the presence of the credential file (never its contents) decides.
    monkeypatch.setattr("aihub_agents.worker._cli_identity", lambda kind, path: ("unavailable", None))
    claude_dir = tmp_path / "claude"
    codex_dir = tmp_path / "codex"
    claude_dir.mkdir()
    codex_dir.mkdir()
    (claude_dir / ".credentials.json").write_text("fixture", encoding="utf-8")
    worker = Worker("http://control", "worker-a", "token")
    calls = []

    async def request(_client, method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if method == "GET":
            return Response(payload=[
                {"id": "claude", "kind": "claude_code_subscription", "config_dir": str(claude_dir)},
                {"id": "codex", "kind": "codex_subscription", "config_dir": str(codex_dir)},
            ])
        return Response()

    worker._request = request
    asyncio.run(worker.check_account_statuses(object()))
    assert calls[-3:] == [
        ("POST", "/api/v0/accounts/claude/status", {"status": "connected"}),
        ("POST", "/api/v0/accounts/codex/status", {"status": "pending_login"}),
        ("POST", "/api/v0/workers/worker-a/found-logins", {"logins": []}),
    ]


def test_flush_sends_per_session_batches_and_keeps_order_on_failure():
    worker = Worker("http://control", "worker-a", "token")
    worker._event_buffer = [("s1", "a", {"n": 1}), ("s1", "a", {"n": 2}), ("s2", "b", {"n": 3})]
    sent = []

    async def fake_request(client, method, path, **kwargs):
        sent.append((path, [event["n"] for event in kwargs["json"]]))
        return None if path.endswith("s2/events") else object()

    worker._request = fake_request
    asyncio.run(worker._flush_events(None))
    assert sent == [("/api/v0/sessions/s1/events", [1, 2]), ("/api/v0/sessions/s2/events", [3])]
    assert worker._event_buffer == [("s2", "b", {"n": 3})]


def test_event_keys_differ_between_runs_of_the_same_session():
    worker = Worker("http://control", "worker-a", "token")
    keys = []

    async def fake_request(client, method, path, **kwargs):
        keys.append(kwargs["json"][0]["client_event_id"])
        return Response(200, [])

    worker._request = fake_request
    for _ in range(2):  # a resumed orchestrator runs again under the same session id
        worker._run_ids["s1"] = __import__("uuid").uuid4().hex[:12]
        asyncio.run(worker._post_event(None, "s1", "s1", 0, {"kind": "output", "payload": {}}))
    assert keys[0] != keys[1] and all(key.startswith("s1:") and key.endswith(":0") for key in keys)


def test_worker_trusts_the_cli_when_it_answers(tmp_path, monkeypatch):
    # The CLI says who is logged in (or that nobody is); a stale credential file does not override it.
    answers = {"claude_code_subscription": ("pending_login", None),
               "codex_subscription": ("connected", {"email": "a@example.com"})}
    monkeypatch.setattr("aihub_agents.worker._cli_identity", lambda kind, path: answers[kind])
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    (claude_dir / ".credentials.json").write_text("stale", encoding="utf-8")
    worker = Worker("http://control", "worker-a", "token")
    calls = []

    async def request(_client, method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if method == "GET":
            return Response(payload=[
                {"id": "claude", "kind": "claude_code_subscription", "config_dir": str(claude_dir)},
                {"id": "codex", "kind": "codex_subscription", "config_dir": str(tmp_path / "codex")},
            ])
        return Response()

    worker._request = request
    asyncio.run(worker.check_account_statuses(object()))
    statuses = {path.split("/")[-2]: body for method, path, body in calls if path.endswith("/status")}
    assert statuses["claude"] == {"status": "pending_login"}
    assert statuses["codex"] == {"status": "connected", "identity": {"email": "a@example.com"}}
