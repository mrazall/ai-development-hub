from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    payload: dict[str, Any]
    source: str = "cli_parser"


class EngineAdapter:
    async def start(self) -> AsyncIterator[AgentEvent]:
        raise NotImplementedError

    async def send(self, text: str) -> None:
        raise NotImplementedError

    async def interrupt(self) -> None:
        raise NotImplementedError


class MockAdapter(EngineAdapter):
    """Deterministic adapter used by integration tests and local demos."""

    def __init__(self, scenario: str = "success", prompt: str = "", workdir=None):
        self.scenario = scenario
        self.prompt = prompt
        self.workdir = workdir
        self._stopped = False
        self._stop_event = asyncio.Event()
        self._messages: asyncio.Queue[str] = asyncio.Queue()

    async def start(self) -> AsyncIterator[AgentEvent]:
        yield AgentEvent("session.status", {"status": "running"}, "native")
        if self.scenario == "hang":
            while not self._stopped:
                await asyncio.sleep(0.05)
            return
        if self.scenario == "echo":
            while not self._stopped:
                message_task = asyncio.create_task(self._messages.get())
                stop_task = asyncio.create_task(self._stop_event.wait())
                done, pending = await asyncio.wait(
                    (message_task, stop_task), return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if self._stop_event.is_set():
                    return
                text = done.pop().result()
                yield AgentEvent("message", {"role": "assistant", "text": f"echo: {text}"}, "native")
                yield AgentEvent("session.status", {"status": "completed"}, "native")
                return
        if self.scenario == "error":
            yield AgentEvent("output", {"text": "mock failure", "stream": "stderr"})
            yield AgentEvent("session.status", {"status": "failed", "reason": "mock failure"})
            return
        if self.scenario == "write" and self.workdir is not None:
            # An executor that changes a file (the worker then commits it on the branch).
            from pathlib import Path

            target = Path(self.workdir) / "mock-output.txt"
            target.write_text(f"{self.prompt}\n", encoding="utf-8")
            yield AgentEvent("message", {"role": "assistant", "text": "wrote mock-output.txt"}, "native")
            yield AgentEvent("session.status", {"status": "completed"}, "native")
            return
        if self.scenario == "limit":
            # A provider limit hit, as Claude reports it (auto-resume is scheduled from this text).
            yield AgentEvent("message", {"role": "assistant", "text": "You've hit your session limit · resets 12am (UTC)"}, "native")
            yield AgentEvent("session.status", {"status": "failed", "exit_code": 1, "engine_session_ref": "mock-ref"}, "native")
            return
        if self.scenario == "echo_prompt":
            yield AgentEvent("message", {"role": "assistant", "text": self.prompt}, "native")
            yield AgentEvent("session.status", {"status": "completed"}, "native")
            return
        yield AgentEvent("message", {"role": "assistant", "text": "mock completed"}, "native")
        yield AgentEvent("session.status", {"status": "completed"}, "native")

    async def send(self, text: str) -> None:
        await self._messages.put(text)

    async def interrupt(self) -> None:
        self._stopped = True
        self._stop_event.set()


class _JsonLinesAdapter(EngineAdapter):
    def __init__(
        self,
        command: list[str],
        env_name: str,
        config_dir: str | None = None,
        workdir: str | Path | None = None,
        accepts_input: bool = True,
        extra_env: dict[str, str] | None = None,
    ):
        self.command, self.env_name, self.config_dir = command, env_name, config_dir
        self.workdir = str(workdir) if workdir else None
        self.accepts_input = accepts_input
        self.extra_env = dict(extra_env or {})
        self.process: asyncio.subprocess.Process | None = None
        self.rate_limits: list[dict[str, Any]] = []
        self._partial_text = ""
        self._last_partial_at = 0.0

    async def start(self) -> AsyncIterator[AgentEvent]:
        env = os.environ.copy()
        if self.config_dir:
            env[self.env_name] = os.path.expanduser(self.config_dir)  # profiles are stored as ~/.aihub/accounts/...
        env.update(self.extra_env)
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE if self.accepts_input else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=self.workdir,
            start_new_session=True,
            limit=32 * 1024 * 1024,  # stream-json lines with big tool results exceed asyncio's 64 KiB default
        )
        assert self.process.stdout is not None
        # The state machine rejects starting -> completed, so announce running once the process exists.
        yield AgentEvent("session.status", {"status": "running"}, "native")
        completion_seen = False
        engine_session_ref: str | None = None
        context_tokens: int | None = None
        async for raw in self.process.stdout:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                yield AgentEvent("output", {"text": raw.decode(errors="replace").rstrip()})
                continue
            engine_session_ref = claude_session_id(value) or engine_session_ref
            delta = partial_text_delta(value)
            if delta is not None:
                self._partial_text += delta
                now = time.monotonic()
                # Each partial is a stored event carrying the whole text so far; 0.5 s keeps it smooth but cheap.
                if now - self._last_partial_at >= 0.5:
                    self._last_partial_at = now
                    yield AgentEvent("message", {"role": "assistant", "text": self._partial_text, "partial": True}, "native")
                continue
            if self._partial_text:
                yield AgentEvent("message", {"role": "assistant", "text": self._partial_text, "partial": True}, "native")
                self._partial_text = ""
            if value_type(value) == "rate_limit_event":
                self.rate_limits = parse_claude_rate_limits(value)
                continue
            if value_type(value) == "result" and isinstance(value.get("usage"), dict):
                context_tokens = context_tokens_from_usage(value["usage"])
            if value_type(value) in {"turn.completed", "result"}:
                completion_seen = True
            for event in map_events(value):
                yield event
        return_code = await self.process.wait()
        if completion_seen and return_code == 0:
            payload: dict[str, Any] = {"status": "completed"}
            if engine_session_ref:
                payload["engine_session_ref"] = engine_session_ref
            if context_tokens is not None:
                payload["context_tokens"] = context_tokens
            yield AgentEvent("session.status", payload, "native")
        elif return_code != 0:
            payload = {"status": "failed", "exit_code": return_code}
            if engine_session_ref:
                payload["engine_session_ref"] = engine_session_ref
            if context_tokens is not None:
                payload["context_tokens"] = context_tokens
            yield AgentEvent("session.status", payload, "native")

    async def send(self, text: str) -> None:
        if not self.accepts_input:
            raise RuntimeError("engine does not accept messages during execution")
        if self.process and self.process.stdin:
            self.process.stdin.write((text + "\n").encode())
            await self.process.stdin.drain()

    async def interrupt(self) -> None:
        if self.process and self.process.returncode is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except TimeoutError:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await self.process.wait()


def value_type(value: dict[str, Any]) -> str:
    return str(value.get("type") or value.get("event") or "output")


def value_payload(value: dict[str, Any]) -> dict[str, Any]:
    return value.get("payload") if isinstance(value.get("payload"), dict) else value


def _tool_summary(value: Any) -> str:
    """One short line for the UI: the most telling argument of a tool call (query, command, path)."""
    if isinstance(value, dict):
        for key in ("query", "command", "file_path", "path", "pattern", "url", "document_id", "title"):
            if value.get(key):
                return str(value[key])[:160]
        return ", ".join(f"{key}={str(item)[:40]}" for key, item in list(value.items())[:3])[:160]
    return str(value or "")[:160]


def _bounded_output(value: Any) -> str:
    return str(value or "")[:8192]


def map_events(value: dict[str, Any]) -> list[AgentEvent]:
    """Map Codex JSONL and Claude stream-json records to contract events.

    Engine-specific fields are deliberately retained only under ``raw_type`` and
    the small contract payload needed by the UI. Unknown records remain visible
    as technical output instead of being silently discarded.
    """
    raw_type = value_type(value)
    item = value.get("item") if isinstance(value.get("item"), dict) else value_payload(value)
    item_type = str(item.get("type", raw_type)) if isinstance(item, dict) else raw_type
    base = {"raw_type": raw_type}
    session_id = claude_session_id(value)
    if session_id:
        base["engine_session_ref"] = session_id
    if raw_type in {"thread.started", "turn.started", "server.connected"}:
        return []
    if raw_type in {"stream_event", "rate_limit_event"}:
        return []
    if raw_type == "turn.completed":
        payload = dict(base)
        if isinstance(value.get("usage"), dict):
            payload["usage"] = value["usage"]
        return [AgentEvent("message", payload, "native")]
    if raw_type in {"assistant", "user"}:
        # Claude stream-json nests tool_use (assistant) and tool_result (user) blocks inside the message.
        message = value.get("message", value.get("content", {}))
        content = message.get("content", []) if isinstance(message, dict) else message
        if not isinstance(content, list):
            text = str(content or "")
            return [AgentEvent("message", {**base, "role": "assistant", "text": text}, "native")] if text and raw_type == "assistant" else []
        events: list[AgentEvent] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                events.append(AgentEvent("tool.call", {
                    **base, "name": str(part.get("name", "tool")), "command": part.get("input", {}),
                    "summary": _tool_summary(part.get("input")),
                }, "native"))
            elif part.get("type") == "tool_result":
                events.append(AgentEvent("tool.result", {
                    **base, "exit_code": 1 if part.get("is_error") else 0, "output": _bounded_output(part.get("content")),
                }, "native"))
        text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text")
        if text and raw_type == "assistant":
            events.append(AgentEvent("message", {**base, "role": "assistant", "text": text}, "native"))
        return events
    if raw_type in {"item.started", "item.updated", "item.completed"}:
        if item_type in {"agent_message", "message"}:
            return [AgentEvent("message", {**base, "role": "assistant", "text": str(item.get("text", ""))}, "native")]
        if item_type == "command_execution":
            command = str(item.get("command", ""))
            if raw_type != "item.completed":
                return [AgentEvent("tool.call", {**base, "name": "shell", "command": command}, "native")]
            return [AgentEvent("tool.result", {**base, "exit_code": item.get("exit_code"), "output": _bounded_output(item.get("aggregated_output", item.get("output")))}, "native")]
        if item_type == "file_change":
            changes = item.get("changes", [])
            return [AgentEvent("diff", {**base, "changes": [{"path": str(change.get("path", "")), "kind": str(change.get("kind", "modified"))} for change in changes if isinstance(change, dict)]}, "native")]
    if raw_type == "tool_use":
        return [AgentEvent("tool.call", {**base, "name": value.get("name", "tool"), "command": value.get("input", {})}, "native")]
    if raw_type == "tool_result":
        return [AgentEvent("tool.result", {**base, "exit_code": value.get("exit_code"), "output": _bounded_output(value.get("content", value.get("output")))}, "native")]
    if raw_type == "result":
        payload = {**base, "text": str(value.get("result", value.get("text", "")))}
        if isinstance(value.get("total_cost_usd"), (int, float)):
            payload["cost_usd"] = float(value["total_cost_usd"])  # API-equivalent cost of the run
        if isinstance(value.get("usage"), dict):
            payload["usage"] = value["usage"]
            context_tokens = context_tokens_from_usage(value["usage"])
            if context_tokens is not None:
                payload["context_tokens"] = context_tokens
        return [AgentEvent("message", {**payload, "role": "assistant"}, "native")]
    return [AgentEvent("output", {**base, "text": _bounded_output(value.get("text", value.get("output", value)))}, "native")]


def from_event(value: dict[str, Any]) -> AgentEvent:
    """Backward-compatible single-record mapper; ignored records become heartbeat."""
    events = map_events(value)
    return events[0] if events else AgentEvent("heartbeat", {"raw_type": value_type(value)}, "native")


def claude_session_id(value: dict[str, Any]) -> str | None:
    """Return Claude's conversation id from init/system or the final result record."""
    candidate = value.get("session_id")
    if isinstance(candidate, str) and candidate:
        return candidate
    # Codex announces its conversation as `thread.started` with a thread id; it is resumable the same way.
    if value.get("type") == "thread.started" and isinstance(value.get("thread_id"), str):
        return value["thread_id"] or None
    payload = value.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("session_id"), str):
        return payload["session_id"] or None
    return None


def partial_text_delta(value: dict[str, Any]) -> str | None:
    """Extract only Claude's official text delta records."""
    if value_type(value) != "stream_event":
        return None
    event = value.get("event") if isinstance(value.get("event"), dict) else value.get("payload")
    if not isinstance(event, dict) or event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return None
    text = delta.get("text")
    return str(text) if isinstance(text, str) else None


def parse_claude_rate_limits(value: dict[str, Any]) -> list[dict[str, Any]]:
    info = value.get("rate_limit_info")
    if not isinstance(info, dict):
        return []
    windows = info.get("unifiedWindows")
    if not isinstance(windows, dict):
        return []
    result = []
    for kind, window in (("five_hour", windows.get("five_hour")), ("seven_day", windows.get("seven_day"))):
        if isinstance(window, dict) and isinstance(window.get("utilization"), (int, float)):
            result.append({"kind": kind, "used_percent": float(window["utilization"]) * 100, "resets_at": window.get("resetsAt")})
    return result


def context_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    """Calculate the prompt context footprint, excluding output tokens."""
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    values = [usage.get(key) for key in keys]
    if not any(isinstance(value, (int, float)) for value in values):
        return None
    return sum(int(value or 0) for value in values)


def extract_claude_metadata(records: list[dict[str, Any]]) -> tuple[str | None, int | None]:
    """Extract the latest conversation id and final result context size from JSONL."""
    session_id = None
    context_tokens = None
    for record in records:
        session_id = claude_session_id(record) or session_id
        if value_type(record) == "result" and isinstance(record.get("usage"), dict):
            context_tokens = context_tokens_from_usage(record["usage"])
    return session_id, context_tokens


class CodexExecAdapter(_JsonLinesAdapter):
    def __init__(
        self,
        config_dir: str | None = None,
        workdir: str | Path | None = None,
        model: str | None = None,
        prompt: str | None = None,
        resume: str | None = None,
    ):
        if resume:
            # `exec resume` has no --cd/--sandbox: the process cwd is the workdir, the sandbox goes via -c.
            command = ["codex", "exec", "resume", "--json", "-c", 'sandbox_mode="workspace-write"', "--skip-git-repo-check"]
        else:
            command = ["codex", "exec", "--json"]
            if workdir:
                command += ["--cd", str(workdir)]
            command += ["--sandbox", "workspace-write", "--skip-git-repo-check"]
        if model:
            command += ["-m", model]
        if resume:
            command += [resume]
        if prompt:
            command += ["--", prompt] if not resume else [prompt]
        super().__init__(command, "CODEX_HOME", config_dir, workdir, accepts_input=False)


CHAT_TOOLS = "Read Edit Write Bash Glob Grep WebFetch WebSearch"


class ClaudeCodeAdapter(_JsonLinesAdapter):
    def __init__(
        self,
        config_dir: str | None = None,
        workdir: str | Path | None = None,
        model: str | None = None,
        prompt: str | None = None,
        resume: str | None = None,
        max_turns: int | None = None,
        disable_tools: bool = False,
        mcp_config: str | Path | None = None,
        append_system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        add_dirs: list[str] | None = None,
        effort: str | None = None,
        permission_mode: str = "edits",
        lean_tools: bool = True,
    ):
        # edits: file edits pre-approved, anything else silently denied (nobody can answer a prompt in -p mode);
        # ask: every other action goes to the owner through the hub MCP permission tool;
        # auto: Claude's auto mode (a classifier allows routine actions and blocks risky ones);
        # all: everything allowed (the owner chose it for this session).
        mode = {"auto": "auto", "all": "bypassPermissions"}.get(permission_mode, "acceptEdits")
        command = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--permission-mode", mode]
        if permission_mode == "ask" and mcp_config:
            command += ["--permission-prompt-tool", "mcp__knowledge__permission_request"]
        # Owner's choice: Opus at low effort (fewer thinking tokens → slower drain of the subscription limits).
        # A chat may choose its own effort; otherwise the worker default.
        command += ["--effort", effort or os.environ.get("AIHUB_CLAUDE_EFFORT", "low")]
        if model:
            command += ["--model", model]
        if resume:
            command += ["--resume", resume]
        if max_turns is not None:
            command += ["--max-turns", str(max_turns)]
        if disable_tools:
            command += ["--disallowedTools", "*", "--max-turns", "1"] if max_turns is None else ["--disallowedTools", "*"]
        if mcp_config:
            # Chat sessions: a lean built-in tool set and only our MCP servers. Measured 24.10 on
            # Claude Code 2.1.308: ~19.5k → ~8.5k context tokens per turn.
            command += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
            if lean_tools:  # not for a workspace session that has the MCP server only to ask for permissions
                command += ["--disable-slash-commands", "--tools", CHAT_TOOLS]
        if append_system_prompt:
            command += ["--append-system-prompt", append_system_prompt]
        if allowed_tools:
            command += ["--allowedTools", *allowed_tools]
        for directory in add_dirs or []:
            command += ["--add-dir", os.path.expanduser(directory)]
        # Prompt is user-controlled text: after "--" so a leading "-" can never be parsed as a CLI flag.
        command += ["--", prompt or ""]
        super().__init__(command, "CLAUDE_CONFIG_DIR", config_dir, workdir, accepts_input=False, extra_env=extra_env)


class CodemanAdapter(EngineAdapter):
    def __init__(
        self,
        base_url: str,
        workspace_ref: str | None = None,
        workdir: str | Path | None = None,
        prompt: str | None = None,
        client: Any | None = None,
    ):
        from .codeman import CodemanClient

        self.base_url, self.workspace_ref = base_url.rstrip("/"), workspace_ref
        self.workdir, self.prompt = (str(workdir) if workdir else None), prompt
        self.session_ref: str | None = None
        self.client = client or CodemanClient(self.base_url)

    async def start(self) -> AsyncIterator[AgentEvent]:
        self.session_ref = await asyncio.to_thread(
            self.client.create_session, "codeman", self.workdir or ".", self.prompt or ""
        )
        payload = {"status": "running", "external_ref": self.session_ref}
        if self.workspace_ref:
            payload["workspace_ref"] = self.workspace_ref
        yield AgentEvent("session.status", payload, "native")
        events = iter(self.client.iter_events(self.session_ref))
        while True:
            event = await asyncio.to_thread(_next_or_none, events)
            if event is None:
                return
            status = _codeman_status(event)
            if status:
                yield AgentEvent(
                    "session.status", {**event.payload, "status": status}, event.source
                )
                if status in {"completed", "failed"}:
                    return
            else:
                yield event

    async def send(self, text: str) -> None:
        if not self.session_ref:
            raise RuntimeError("Codeman session has not started")
        await asyncio.to_thread(self.client.send_input, self.session_ref, text)

    async def interrupt(self) -> None:
        if self.session_ref:
            await asyncio.to_thread(self.client.stop_session, self.session_ref)


def _codeman_status(event: AgentEvent) -> str | None:
    """Extract terminal state from Codeman's event payload without assuming one event name."""
    status = event.payload.get("status") or event.payload.get("state")
    if isinstance(status, str):
        normalized = status.lower()
        if normalized in {"completed", "complete", "done", "finished", "success", "succeeded"}:
            return "completed"
        if normalized in {"failed", "failure", "error", "aborted", "cancelled", "canceled"}:
            return "failed"
    if event.kind.lower() in {"session:completed", "session:complete", "session:done"}:
        return "completed"
    if event.kind.lower() in {"session:failed", "session:error", "session:aborted"}:
        return "failed"
    return None


def _next_or_none(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def ensure_allowed_workdir(workdir: str, allowed_paths: list[str]) -> Path:
    candidate = Path(workdir).expanduser().resolve(strict=False)
    roots = [Path(root).expanduser().resolve(strict=False) for root in allowed_paths]
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise ValueError("workdir is outside project allowed_paths")
    return candidate


def safe_path(workdir: Path, requested: str, max_bytes: int = 1_048_576) -> Path:
    if not requested or Path(requested).is_absolute():
        raise ValueError("path must be relative")
    candidate = (workdir / requested).resolve(strict=False)
    if candidate != workdir and workdir not in candidate.parents:
        raise ValueError("path escapes session workdir")
    if candidate.is_symlink():
        raise ValueError("symlinks are not allowed")
    if candidate.is_file() and candidate.stat().st_size > max_bytes:
        raise ValueError("file exceeds 1 MiB")
    return candidate
