from __future__ import annotations

import argparse
import asyncio
import subprocess
import uuid
import json
import os
import re
import shutil
import signal
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .adapters import (
    CHAT_TOOLS,
    ClaudeCodeAdapter,
    CodemanAdapter,
    CodexExecAdapter,
    EngineAdapter,
    MockAdapter,
    ensure_allowed_workdir,
)
from .mcp_config import write_claude_session_config, write_session_config
from .rate_limits import latest_codex_rollout_rate_limits
from .workspace import commit_worktree, execute_request, make_project_dir, prepare_worktree, safe_path, merge_branch


class Worker:
    def __init__(
        self, control_plane: str, worker_id: str, token: str, codeman_url: str | None = None,
        enabled_engines: set[str] | None = None, max_session_seconds: int = 3600
    ):
        self.base = control_plane.rstrip("/")
        self.worker_id, self.token, self.codeman_url = worker_id, token, codeman_url
        self.enabled_engines = enabled_engines or set()
        self.max_session_seconds = max_session_seconds
        self.headers = {"Authorization": f"Bearer {token}"}
        self._active_adapters: set[Any] = set()
        self._active_sessions: set[str] = set()
        self._run_ids: dict[str, str] = {}
        self._event_buffer: list[tuple[str, str, dict[str, Any]]] = []
        self._flush_task: asyncio.Task | None = None
        self._account_task: asyncio.Task | None = None
        self._last_account_check = 0.0
        self._running: dict[str, asyncio.Task[None]] = {}
        self.max_parallel = int(os.environ.get("AIHUB_WORKER_MAX_PARALLEL", "6"))
        self.token_file = os.environ.get("AIHUB_HUB_TOKEN_FILE")
        # Roots where the hub may create project folders (colon-separated); default ~/projects.
        self.workspace_roots = os.environ.get("AIHUB_WORKSPACE_ROOTS", "~/projects").split(":")

    def refresh_token(self) -> None:
        if not self.token_file:
            return
        value = Path(self.token_file).read_text(encoding="utf-8").strip()
        if value:
            self.token = value
            self.headers = {"Authorization": f"Bearer {value}"}

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs):
        """Make control-plane calls retryable without retrying client errors."""
        self.refresh_token()
        for attempt in range(5):
            try:
                response = await client.request(method, f"{self.base}{path}", **kwargs)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError("control plane unavailable", request=response.request, response=response)
                return response
            except httpx.HTTPError:
                if attempt == 4:
                    return None
                await asyncio.sleep(min(2**attempt, 60))
        return None

    async def capabilities(self) -> None:
        engines = {}
        executables = {"claude_code": "claude", "codex": "codex", "opencode": "opencode", "codeman": "codeman"}
        for name, executable in executables.items():
            if name not in self.enabled_engines:
                continue
            path = shutil.which(executable)
            if path:
                engines[name] = (
                    await asyncio.create_subprocess_exec(
                        path, "--version", stdout=asyncio.subprocess.PIPE
                    )
                ).stdout
        versions = {}
        for name, stream in engines.items():
            if stream:
                versions[name] = (await stream.read()).decode(errors="replace").strip()[:200]
        payload = {"engines": versions}
        if self.codeman_url:
            payload["workspace_url"] = self.codeman_url
        async with httpx.AsyncClient() as client:
            await self._request(
                client, "POST", f"/api/v0/workers/{self.worker_id}/capabilities",
                headers=self.headers, json=payload,
            )

    async def _heartbeat_loop(self, client: httpx.AsyncClient) -> None:
        interval = 5
        while True:
            # One quick attempt per tick: retry backoff here would outlast the lease while the hub restarts.
            self.refresh_token()
            try:
                response = await client.post(
                    f"{self.base}/api/v0/workers/{self.worker_id}/heartbeat", headers=self.headers,
                    json={"active_sessions": sorted(self._active_sessions)},  # lets the hub undo a false "offline"
                    timeout=10,
                )
            except httpx.HTTPError:
                response = None
            if response is not None and response.is_success:
                interval = max(1, min(20, int(response.json().get("lease_ttl_s", 60) / 3)))
            # Flush in the background: a large backlog must never delay the next heartbeat.
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = asyncio.create_task(self._flush_events(client))
            if time.monotonic() - self._last_account_check >= 60 and (
                self._account_task is None or self._account_task.done()
            ):
                self._account_task = asyncio.create_task(self.check_account_statuses(client))
            await asyncio.sleep(interval)

    async def _commit_executor_work(self, client: httpx.AsyncClient, session: dict, assignment_id: str, workdir) -> None:
        title = str(session.get("title") or "executor").strip()[:72]
        try:
            message = f"{title}\n\nCommitted by the AI Hub worker for executor {session['id']}."
            sha = await asyncio.to_thread(commit_worktree, str(workdir), message)
            text = f"Изменения закоммичены в {session.get('branch')}: {sha}" if sha else "Изменений для коммита нет."
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            text = f"Коммит не удался: {exc}"
        await self._post_event(client, session["id"], assignment_id, 0, {
            "kind": "output", "source": "heartbeat", "payload": {"text": text, "stream": "stdout"},
        })

    async def check_account_statuses(self, client: httpx.AsyncClient) -> None:
        """Check only credential file existence; never read or log credential contents."""
        response = await self._request(
            client, "GET", f"/api/v0/workers/{self.worker_id}/accounts", headers=self.headers
        )
        if response is None or not response.is_success:
            return
        for account in response.json():
            config_dir = account.get("config_dir")
            _ensure_profile_dir(config_dir)
            if account.get("kind") == "claude_code_subscription":
                ready = bool(config_dir and (Path(config_dir).expanduser() / ".credentials.json").is_file())
            elif account.get("kind") == "codex_subscription":
                ready = bool(config_dir and (Path(config_dir).expanduser() / "auth.json").is_file())
            else:
                continue
            await self._request(
                client, "POST", f"/api/v0/accounts/{account['id']}/status",
                headers=self.headers, json={"status": "connected" if ready else "pending_login"}  # server statuses: schemas.ACCOUNT_STATUSES,
            )
        self._last_account_check = time.monotonic()

    async def stop(self) -> None:
        adapters = tuple(self._active_adapters)
        if adapters:
            await asyncio.gather(*(adapter.interrupt() for adapter in adapters), return_exceptions=True)

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            await self._request(client, "POST", f"/api/v0/workers/{self.worker_id}/recover", headers=self.headers)
            await self.check_account_statuses(client)
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(client))
            terminal_task = None
            if os.environ.get("AIHUB_WORKER_TERMINAL", "1") != "0":  # embedded terminal channel to the hub
                from .terminal import TerminalChannel

                terminal_task = asyncio.create_task(
                    TerminalChannel(self.base, self.worker_id, lambda: self.token).run()
                )
            try:
                while True:
                    response = await self._request(
                        client, "GET", f"/api/v0/{self.worker_id}/assignments", headers=self.headers
                    )
                    if response is not None and response.is_success:
                        # Assignments run concurrently: an orchestrator waits for its executors, which must
                        # be able to start on the same worker (sequential runs deadlocked).
                        for assignment in response.json():
                            key = str(assignment.get("id"))
                            if key in self._running or len(self._running) >= self.max_parallel:
                                continue
                            task = asyncio.create_task(self.run_assignment(client, assignment))
                            self._running[key] = task
                            task.add_done_callback(lambda _task, key=key: self._running.pop(key, None))
                    await self.service_workspace_request(client)
                    await asyncio.sleep(5)
            finally:
                heartbeat_task.cancel()
                if terminal_task:
                    terminal_task.cancel()
                await asyncio.gather(heartbeat_task, *([terminal_task] if terminal_task else []), return_exceptions=True)
                await self.stop()
                if self._running:
                    await asyncio.gather(*self._running.values(), return_exceptions=True)

    async def service_workspace_request(self, client: httpx.AsyncClient) -> None:
        response = await self._request(
            client, "GET", f"/api/v0/workers/{self.worker_id}/requests/next", headers=self.headers
        )
        if response is None or not response.is_success or not response.json():
            return
        request = response.json()
        if request.get("kind") == "limits_refresh":
            await self._refresh_limits(client, request)
            return
        try:
            if request.get("kind") == "git_merge":
                params = request.get("response") or {}
                result = await asyncio.to_thread(
                    merge_branch, request["workdir"], request.get("path") or "", str(params.get("base_branch") or "main")
                )
            elif request.get("kind") == "mkdir":
                result = await asyncio.to_thread(make_project_dir, request.get("path") or "", self.workspace_roots)
            else:
                result = await asyncio.to_thread(
                    execute_request, request["workdir"], request["kind"], request.get("path")
                )
            payload = {"result": result}
        except (OSError, RuntimeError, ValueError) as exc:
            payload = {"error": str(exc)[:500]}
        await self._request(
            client, "POST", f"/api/v0/workers/{self.worker_id}/requests/{request['id']}/response",
            headers=self.headers, json=payload,
        )

    async def _refresh_limits(self, client: httpx.AsyncClient, request: dict[str, Any]) -> None:
        """Run the explicitly requested, minimal subscription probe and always answer the request."""
        payload = request.get("response") or {}
        account_id = payload.get("account_id")
        result: dict[str, Any] = {"error": "account id missing"}
        try:
            account_response = await self._request(
                client, "GET", f"/api/v0/accounts/{account_id}", headers=self.headers
            ) if account_id else None
            if account_response is None or not account_response.is_success:
                result = {"error": "account unavailable"}
            else:
                account = account_response.json()
                kind = account.get("kind")
                adapter: EngineAdapter | None = None
                if kind == "claude_code_subscription":
                    adapter = ClaudeCodeAdapter(account.get("config_dir"), prompt="ok", max_turns=1, disable_tools=True)
                elif kind == "codex_subscription":
                    adapter = CodexExecAdapter(account.get("config_dir"), prompt="ok")
                if adapter is None:
                    result = {"error": f"unsupported account kind {kind}"}
                else:
                    tail: list[str] = []
                    started = time.time()
                    async for event in adapter.start():
                        if event.kind == "output":
                            tail = (tail + [str(event.payload.get("text", ""))[:200]])[-3:]
                    windows = getattr(adapter, "rate_limits", None) or []
                    if not windows and kind == "codex_subscription":
                        # Codex keeps them in its own rollout journal, not in `exec --json` output.
                        windows = latest_codex_rollout_rate_limits(_codex_base_home(account.get("config_dir")), started)
                    if windows:
                        posted = await self._request(
                            client, "POST", f"/api/v0/accounts/{account_id}/limits", headers=self.headers,
                            json={"captured_at": datetime.now(UTC).isoformat(), "windows": windows},
                        )
                        result = {"windows": len(windows), "status": None if posted is None else posted.status_code}
                    else:
                        result = {"error": "CLI reported no rate limits", "tail": tail}
        except Exception as exc:  # noqa: BLE001 - reported back instead of silently stalling the request
            result = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        print(f"limits refresh {account_id}: {result}", flush=True)
        await self._request(
            client, "POST", f"/api/v0/workers/{self.worker_id}/requests/{request['id']}/response",
            headers=self.headers, json={"result": result} if "error" not in result else {"error": str(result)[:500]},
        )

    async def run_assignment(self, client: httpx.AsyncClient, assignment: dict) -> None:
        self._run_ids[str(assignment["id"])] = uuid.uuid4().hex[:12]
        response = await self._request(
            client, "POST", f"/api/v0/assignments/{assignment['id']}/claim", headers=self.headers
        )
        if response is None or response.status_code != 200:
            return
        session = response.json()
        engine = session.get("engine", "")
        if not engine.startswith("mock") and engine not in self.enabled_engines:
            await self._fail(client, session["id"], assignment["id"], "engine not enabled on this worker")
            return
        try:
            workdir = ensure_allowed_workdir(session.get("workdir", ""), session.get("allowed_paths", []))
        except (TypeError, ValueError, OSError) as exc:
            await self._fail(client, session["id"], assignment["id"], str(exc))
            return
        prompt = str(session.get("task_body") or session.get("task_title") or session.get("title") or "").strip()
        if session.get("role") == "executor" and session.get("orchestration"):
            orchestration = session["orchestration"]
            try:
                await asyncio.to_thread(
                    prepare_worktree,
                    orchestration.get("base_workdir") or workdir,
                    workdir,
                    session.get("branch") or "",
                    orchestration.get("base_branch") or "main",
                )
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                await self._fail(client, session["id"], assignment["id"], f"worktree setup failed: {exc}")
                return
        incoming = await self._request(
            client, "GET", f"/api/v0/assignments/{session['id']}/events",
            params={"after": 0}, headers=self.headers,
        )
        user_messages = [
            event for event in (incoming.json() if incoming is not None and incoming.is_success else [])
            if event.get("kind") == "message" and event.get("payload", {}).get("role") == "user"
        ]
        # A resumed run (an orchestrator continued in place) answers the newest message, not the original task.
        resuming = bool(session.get("engine_session_ref"))
        initial_event = (user_messages[-1] if resuming else user_messages[0]) if user_messages else None
        if initial_event:
            prompt = str(initial_event.get("payload", {}).get("text", "")).strip() or prompt
        if not prompt:
            await self._fail(client, session["id"], assignment["id"], "session prompt is empty")
            return
        await self._post_event(
            client, session["id"], assignment["id"], -1,
            {"kind": "session.status", "source": "native", "payload": {"status": "starting"}},
        )
        attachment_links = await self._download_attachments(
            client, session, assignment["id"], None, workdir
        )
        if attachment_links:
            prompt += "\n\nПользователь приложил файлы:\n" + "\n".join(attachment_links)
        config_dir = None
        session_mcp_path: Path | None = None
        session_mcp_dir: Path | None = None
        session_token_file: Path | None = None
        codex_overlay: Path | None = None
        codex_home_for_limits: Path | None = None
        if session.get("account_profile_id"):
            account_response = await self._request(
                client, "GET", f"/api/v0/accounts/{session['account_profile_id']}", headers=self.headers
            )
            if account_response is None or not account_response.is_success:
                await self._fail(client, session["id"], assignment["id"], "account profile unavailable")
                self._cleanup_attachment_dir(workdir, session["id"])
                return
            config_dir = account_response.json().get("config_dir")
        if engine in {"codex", "claude_code"}:
            try:
                if engine == "codex":
                    # Outside the workdir (the agent must not see it); the overlay links the base
                    # profile (auth, history) and only replaces config.toml.
                    codex_home_for_limits = _codex_base_home(config_dir)
                    codex_overlay = Path(tempfile.mkdtemp(prefix="aihub-codex-"))
                    scratch = codex_overlay / ".mcp"
                    mcp_file = await asyncio.to_thread(
                        write_session_config,
                        workdir,
                        self.base,
                        session.get("project_id", ""),
                        engine,
                        self.token,
                        codex_home=scratch,
                    )
                    mcp_toml = mcp_file.read_text(encoding="utf-8")
                    shutil.rmtree(scratch, ignore_errors=True)
                    if "[mcp_servers" not in mcp_toml:
                        shutil.rmtree(codex_overlay, ignore_errors=True)
                        codex_overlay = None
                    else:
                        _build_codex_overlay(codex_overlay, _codex_base_home(config_dir), mcp_toml)
                        config_dir = str(codex_overlay)
                elif session.get("mcp_config"):
                    session_mcp_dir = Path(tempfile.mkdtemp(prefix="aihub-mcp-"))
                    session_token_file = session_mcp_dir / "hub-token"
                    await asyncio.to_thread(write_token_file, session_token_file, str(session.get("knowledge_token") or ""))
                    session_mcp_path = await asyncio.to_thread(
                        write_claude_session_config,
                        session_mcp_dir,
                        session["mcp_config"],
                        str(session.get("hub_url") or ""),
                        str(session.get("knowledge_token") or ""),
                        token_file=session_token_file,
                        orchestrator_session=session["id"] if session.get("role") == "orchestrator" else None,
                        permission_session=session["id"] if session.get("permission_mode") == "ask" else None,
                    )
            except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
                warning = re.sub(r"\$\{[^}]+\}", "${REDACTED}", str(exc))
                await self._post_event(
                    client, session["id"], assignment["id"], -2,
                    {"kind": "output", "source": "heartbeat", "payload": {
                        "text": f"MCP configuration unavailable; continuing without MCP ({warning[:300]})",
                        "stream": "stderr",
                    }},
                )
                if codex_overlay:
                    shutil.rmtree(codex_overlay, ignore_errors=True)
                    codex_overlay = None
                session_mcp_path = None
        continuation_ref = session.get("engine_session_ref")
        compact = (
            engine == "claude_code" and bool(continuation_ref)
            and should_compact_claude(session.get("context_tokens"), bool(session.get("context_fresh")))
        )
        if compact:
            summary = await self._compact_claude_context(
                config_dir, workdir, session.get("model"), continuation_ref
            )
            if summary:
                old_tokens = int(session.get("context_tokens") or 0)
                prompt = (
                    "Сводка предыдущей беседы:\n" + summary
                    + "\n\n--- Сообщение для новой сессии ---\n" + prompt
                )
                await self._post_event(
                    client, session["id"], assignment["id"], -4,
                    {"kind": "message", "source": "native", "payload": {
                        "kind": "context_compacted", "from_tokens": old_tokens,
                        "to_tokens": len(summary.split()),
                    }},
                )
        scenario = "success" if engine == "mock" else engine.removeprefix("mock_")
        adapter = (
            MockAdapter(scenario, prompt, workdir=workdir)
            if engine.startswith("mock")
            else (
                CodexExecAdapter(config_dir, workdir, session.get("model"), prompt, resume=continuation_ref)
                if session.get("engine") == "codex"
                else ClaudeCodeAdapter(
                    config_dir, workdir, session.get("model"), prompt,
                    resume=continuation_ref if not compact else None,
                    mcp_config=session_mcp_path,
                    append_system_prompt=(session.get("mcp_config") or {}).get("append_system_prompt"),
                    effort=(session.get("mcp_config") or {}).get("effort"),
                    permission_mode=session.get("permission_mode") or "edits",
                    lean_tools=bool(session.get("chat_id") or session.get("role") in {"orchestrator", "vault"}),
                    # Orchestrators review and merge executor branches (git) and run tests; non-interactive
                    # Claude needs these pre-approved. Chats keep only the memory tools pre-approved.
                    allowed_tools=(
                        ["mcp__knowledge", "Bash", "Read", "Edit", "Write", "Glob", "Grep"]
                        if session.get("role") == "orchestrator"
                        # Applying an agent draft to the knowledge vault: edit notes and commit, no other shell.
                        else ["mcp__knowledge", "Read", "Edit", "Write", "Glob", "Grep", "Bash(git:*)"]
                        if session.get("role") == "vault"
                        # Owner's choice: a chat is a full assistant — every tool it has is pre-approved
                        # (non-interactive Claude silently denies anything that would need a prompt).
                        else ["mcp__knowledge", *CHAT_TOOLS.split()] if session.get("chat_id")
                        else ["mcp__knowledge"] if session_mcp_path else None
                    ),
                    # Chats start in their own scratch folder but may work anywhere in the home directory.
                    add_dirs=["~"] if session.get("chat_id") else None,
                )
                if session.get("engine") == "claude_code"
                else CodemanAdapter(
                    self.codeman_url or "http://127.0.0.1:3000",
                    session.get("workspace_ref"), workdir, prompt,
                )
            )
        )
        event_task = asyncio.create_task(
            self._forward_events(client, session["id"], assignment["id"], adapter)
        )
        self._active_adapters.add(adapter)
        self._active_sessions.add(session["id"])
        session_started_at = time.time()
        cursor = max((event.get("cursor", 0) for event in (incoming.json() if incoming is not None and incoming.is_success else [])), default=0)
        started_at = time.monotonic()
        last_token_refresh = started_at
        try:
            while not event_task.done():
                if session_token_file and time.monotonic() - last_token_refresh >= 300:
                    renewed = await self._request(
                        client, "POST", f"/api/v0/assignments/{assignment['id']}/token", headers=self.headers
                    )
                    if renewed is not None and renewed.is_success:
                        new_token = renewed.json()["access_token"]
                        await asyncio.to_thread(write_token_file, session_token_file, new_token)
                        await asyncio.to_thread(_replace_mcp_token, session_mcp_path, new_token)
                        last_token_refresh = time.monotonic()
                if time.monotonic() - started_at >= session_timeout_seconds(session, self.max_session_seconds):
                    await adapter.interrupt()
                    event_task.cancel()
                    await asyncio.gather(event_task, return_exceptions=True)
                    await self._fail(client, session["id"], assignment["id"], "timeout")
                    return
                state = await self._request(
                    client, "GET", f"/api/v0/assignments/{session['id']}", headers=self.headers
                )
                if state is not None and state.is_success and state.json().get("status") in {"failed", "completed"}:
                    await adapter.interrupt()
                    break
                incoming = await self._request(
                    client, "GET", f"/api/v0/assignments/{session['id']}/events",
                    params={"after": cursor}, headers=self.headers,
                )
                if incoming is not None and incoming.is_success:
                    for event in incoming.json():
                        cursor = max(cursor, event["cursor"])
                        payload = event.get("payload", {})
                        if event.get("kind") == "message" and payload.get("role") == "user":
                            try:
                                text = str(payload.get("text", ""))
                                attachment_ids = payload.get("attachment_ids", [])
                                if isinstance(attachment_ids, list) and attachment_ids:
                                    links = await self._download_attachments(client, session, assignment["id"], attachment_ids, workdir)
                                    if links:
                                        text += "\n\nПользователь приложил файлы:\n" + "\n".join(links)
                                await adapter.send(text)
                            except RuntimeError as exc:
                                await self._post_event(client, session["id"], assignment["id"], cursor, {
                                    "kind": "output", "source": "heartbeat",
                                    "payload": {"text": str(exc), "stream": "stderr"},
                                })
                # Each tick is two hub requests; at 0.1 s a few agents flooded the hub with ~20 req/s.
                await asyncio.sleep(1.0)
            await event_task
            if session.get("role") == "executor" and session.get("orchestration"):
                await self._commit_executor_work(client, session, assignment["id"], workdir)
            if session.get("account_profile_id") and engine == "codex":
                adapter.rate_limits = latest_codex_rollout_rate_limits(codex_home_for_limits, session_started_at)
            if session.get("account_profile_id") and getattr(adapter, "rate_limits", None):
                await self._request(
                    client, "POST", f"/api/v0/accounts/{session['account_profile_id']}/limits",
                    headers=self.headers,
                    json={"captured_at": datetime.now(UTC).isoformat(), "windows": adapter.rate_limits},
                )
        except (OSError, RuntimeError, httpx.HTTPError) as exc:
            if not event_task.done():
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
            await self._post_event(
                client,
                session["id"],
                assignment["id"],
                0,
                {
                    "kind": "session.status",
                    "source": "heartbeat",
                    "payload": {"status": "failed", "reason": str(exc)[:500]},
                },
            )
        finally:
            self._active_adapters.discard(adapter)
            self._active_sessions.discard(session["id"])
            if session_mcp_path and engine == "claude_code":
                try:
                    session_mcp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if codex_overlay:
                shutil.rmtree(codex_overlay, ignore_errors=True)
            if session_mcp_dir:
                shutil.rmtree(session_mcp_dir, ignore_errors=True)
            self._cleanup_attachment_dir(workdir, session["id"])

    async def _download_attachments(
        self,
        client,
        session: dict,
        message_id: str,
        ids: list | None,
        workdir: Path,
    ) -> list[str]:
        """Download session attachments using the worker-scoped assignment API.

        ``ids=None`` is used before a one-shot engine starts: all files already
        attached to the session are materialized and described in its prompt.
        A message can still provide an explicit subset for interactive engines.
        """
        metadata_response = await self._request(
            client,
            "GET",
            f"/api/v0/assignments/{session['id']}/attachments",
            headers=self.headers,
        )
        if metadata_response is None or not metadata_response.is_success:
            await self._attachment_warning(
                client, session["id"], message_id,
                "вложения сессии недоступны",
            )
            return []
        records = metadata_response.json()
        requested = {str(item) for item in ids} if ids is not None else None
        records = [item for item in records if requested is None or str(item.get("id")) in requested]
        destination = safe_path(workdir, f".aihub/attachments/{session['id']}")
        destination.mkdir(parents=True, exist_ok=True)
        lines = []
        for item in records[:10]:
            attachment_id = str(item.get("id", ""))
            response = await self._request(
                client,
                "GET",
                f"/api/v0/assignments/{session['id']}/attachments/{attachment_id}",
                headers=self.headers,
            )
            if response is None or not response.is_success:
                await self._attachment_warning(
                    client, session["id"], message_id,
                    f"вложение {attachment_id} недоступно",
                )
                continue
            name = re.sub(r"[^\w .()\[\]-]+", "_", str(item.get("original_name") or "attachment"))
            name = Path(name).name.strip(" .") or "attachment"
            target = safe_path(destination, name)
            if target.exists():
                target = safe_path(destination, f"{target.stem}-{attachment_id[:8]}{target.suffix}")
            target.write_bytes(response.content)
            lines.append(
                f"{target.relative_to(workdir)} ({item.get('mime_type', 'application/octet-stream')}, "
                f"{item.get('size_bytes', len(response.content))} bytes)"
            )
        self._ensure_exclude(workdir)
        return lines

    async def _attachment_warning(self, client, session_id: str, assignment_id: str, text: str) -> None:
        await self._post_event(
            client, session_id, assignment_id, -3,
            {"kind": "output", "source": "heartbeat", "payload": {"text": text, "stream": "stderr"}},
        )

    @staticmethod
    def _ensure_exclude(workdir: Path) -> None:
        """Keep generated files out of git, but do nothing for non-git workdirs."""
        git_dir = workdir / ".git"
        if not git_dir.is_dir():
            return
        exclude = git_dir / "info" / "exclude"
        try:
            content = exclude.read_text(encoding="utf-8", errors="ignore") if exclude.exists() else ""
            marker = ".aihub/attachments/"
            if marker not in content:
                exclude.parent.mkdir(parents=True, exist_ok=True)
                with exclude.open("a", encoding="utf-8") as stream:
                    stream.write("\n" + marker + "\n")
        except OSError:
            return

    @staticmethod
    def _cleanup_attachment_dir(workdir: Path, session_id: str) -> None:
        try:
            attachment_dir = safe_path(workdir, f".aihub/attachments/{session_id}")
            shutil.rmtree(attachment_dir, ignore_errors=True)
        except (OSError, ValueError, TypeError):
            pass

    async def _fail(self, client: httpx.AsyncClient, session_id: str, assignment_id: str, reason: str) -> None:
        await self._post_event(
            client, session_id, assignment_id, 0,
            {"kind": "session.status", "source": "heartbeat", "payload": {"status": "failed", "reason": reason[:500]}},
        )

    async def _post_event(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        assignment_id: str,
        index: int,
        event: dict[str, Any],
    ) -> None:
        # The run id keeps keys unique when the same session runs again (a resumed orchestrator);
        # without it the hub dropped the new run's events as duplicates of the old ones.
        run = self._run_ids.get(assignment_id, "")
        event["client_event_id"] = f"{assignment_id}:{run}:{index}" if run else f"{assignment_id}:{index}"
        response = await self._request(
            client, "POST", f"/api/v0/sessions/{session_id}/events",
            headers=self.headers, json=[event]
        )
        if response is None:
            self._event_buffer.append((session_id, assignment_id, event))

    async def _flush_events(self, client: httpx.AsyncClient) -> None:
        pending, self._event_buffer = self._event_buffer, []
        # Send in per-session batches; on failure keep the rest (in order) for the next flush.
        while pending:
            session_id = pending[0][0]
            batch = []
            while pending and pending[0][0] == session_id and len(batch) < 200:
                batch.append(pending.pop(0))
            response = await self._request(
                client, "POST", f"/api/v0/sessions/{session_id}/events",
                headers=self.headers, json=[event for _, _, event in batch]
            )
            if response is None:
                self._event_buffer = batch + pending + self._event_buffer
                return

    async def _forward_events(
        self, client: httpx.AsyncClient, session_id: str, assignment_id: str, adapter
    ) -> None:
        index = 0
        async for event in adapter.start():
            await self._post_event(
                client,
                session_id,
                assignment_id,
                index,
                {
                    "kind": event.kind,
                    "source": event.source,
                    "payload": event.payload,
                },
            )
            index += 1

    async def _compact_claude_context(
        self, config_dir: str | None, workdir: Path, model: str | None, resume: str
    ) -> str:
        adapter = ClaudeCodeAdapter(
            config_dir, workdir, model,
            "Составь сводку для продолжения работы в новой сессии: цель, что сделано, "
            "принятые решения, открытые вопросы, ключевые файлы и команды. "
            "Не более 300 слов, без вступлений.",
            resume=resume, max_turns=1, disable_tools=True,
        )
        parts: list[str] = []
        async for event in adapter.start():
            if event.kind == "message" and event.payload.get("text"):
                parts.append(str(event.payload["text"]))
        return "\n".join(parts).strip()


def _ensure_profile_dir(config_dir: str | None) -> None:
    """Create ~/.aihub/accounts/<id>/<engine> (0700) so the owner only has to log in; nothing else is touched."""
    if not config_dir:
        return
    path = Path(config_dir).expanduser()
    root = (Path.home() / ".aihub" / "accounts").resolve()
    try:
        resolved = path.resolve()
        if root not in resolved.parents:
            return
        resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
        for directory in (resolved.parent, resolved):
            directory.chmod(0o700)
    except OSError:
        return


def _codex_base_home(config_dir: str | None) -> Path:
    return Path(config_dir or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def _build_codex_overlay(overlay: Path, base: Path, mcp_toml: str) -> None:
    """Link every entry of the base Codex profile except config.toml, which gains the session MCP servers."""
    if base.is_dir():
        for entry in base.iterdir():
            if entry.name != "config.toml":
                (overlay / entry.name).symlink_to(entry)
    base_config = base / "config.toml"
    prefix = base_config.read_text(encoding="utf-8") if base_config.is_file() else ""
    (overlay / "config.toml").write_text(prefix.rstrip("\n") + "\n\n" + mcp_toml, encoding="utf-8")


def should_compact_claude(context_tokens: int | None, fresh: bool, limit: int | None = None) -> bool:
    if fresh:
        return True
    if context_tokens is None:
        return False
    configured = limit if limit is not None else int(os.environ.get("AIHUB_CLAUDE_CONTEXT_LIMIT", "250000"))
    return context_tokens >= configured


def session_timeout_seconds(session: dict[str, Any], default: int = 3600) -> int:
    if session.get("role") == "orchestrator":
        configured = int(os.environ.get("AIHUB_ORCHESTRATOR_MAX_SECONDS", "14400"))
        return min(max(configured, 1), 14400)
    return max(int(default), 1)


def write_token_file(path: str | Path, token: str) -> None:
    """Atomically replace a worker token file and keep it private."""
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(token, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)
    target.chmod(0o600)


def _replace_mcp_token(path: Path | None, token: str) -> None:
    if not path or not path.is_file():
        return
    config = json.loads(path.read_text(encoding="utf-8"))
    env = config.get("mcpServers", {}).get("knowledge", {}).get("env", {})
    if "AIHUB_HUB_TOKEN" in env:
        env["AIHUB_HUB_TOKEN"] = token
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-plane", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--codeman-url")
    parser.add_argument("--enable-engines", default="", help="comma-separated real engines")
    parser.add_argument("--max-session-seconds", type=int, default=3600)
    args = parser.parse_args()
    token = Path(args.token_file).read_text().strip()
    enabled = {item.strip() for item in args.enable_engines.split(",") if item.strip()}
    worker = Worker(args.control_plane, args.worker_id, token, args.codeman_url, enabled, args.max_session_seconds)

    async def serve() -> None:
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop_event.set)
        await worker.capabilities()
        task = asyncio.create_task(worker.run())
        await stop_event.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await worker.stop()

    asyncio.run(serve())
