from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
from .workspace import (
    commit_worktree,
    execute_request,
    make_project_dir,
    merge_branch,
    prepare_worktree,
    safe_path,
)


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
        self._active_profile_dirs: set[Path] = set()
        self._run_ids: dict[str, str] = {}
        self._worker_seq: dict[str, int] = {}
        self._hub_problem: str | None = None
        self._event_buffer: list[tuple[str, str, dict[str, Any]]] = []
        self._flush_task: asyncio.Task | None = None
        self._account_task: asyncio.Task | None = None
        self._last_account_check = 0.0
        self._account_last_checks: dict[str, float] = {}
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
                self._note_hub_problem(None)
                return response
            except httpx.HTTPError as exc:
                self._note_hub_problem(describe_hub_error(exc, self.base))
                if attempt == 4:
                    return None
                await asyncio.sleep(min(2**attempt, 60))
        return None

    def _note_hub_problem(self, problem: str | None) -> None:
        """Say in the journal why the hub is unreachable — once per change, not on every retry. The hub only
        shows the worker as offline; the reason (found live: WSL DNS stopped resolving the hub after a reboot)
        is visible only here."""
        if problem == self._hub_problem:
            return
        if problem:
            print(f"hub unreachable: {problem}", flush=True)
        elif self._hub_problem:
            print("hub reachable again", flush=True)
        self._hub_problem = problem

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
            check_interval = 5 if self._account_watch_active() else 60
            if time.monotonic() - self._last_account_check >= check_interval and (
                self._account_task is None or self._account_task.done()
            ):
                self._account_task = asyncio.create_task(self.check_account_statuses(client))
            await asyncio.sleep(interval)

    async def _commit_executor_work(
        self, client: httpx.AsyncClient, session: dict, assignment_id: str, workdir, index: int
    ) -> None:
        title = str(session.get("title") or "executor").strip()[:72]
        try:
            message = f"{title}\n\nCommitted by the AI Hub worker for executor {session['id']}."
            sha = await asyncio.to_thread(commit_worktree, str(workdir), message)
            text = f"Изменения закоммичены в {session.get('branch')}: {sha}" if sha else "Изменений для коммита нет."
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            text = f"Коммит не удался: {exc}"
        await self._post_event(client, session["id"], assignment_id, index, {
            "kind": "output", "source": "heartbeat", "payload": {"text": text, "stream": "stdout"},
        })

    async def check_account_statuses(self, client: httpx.AsyncClient) -> None:
        """Check official CLI status without ever reading credential files."""
        response = await self._request(
            client, "GET", f"/api/v0/workers/{self.worker_id}/accounts", headers=self.headers
        )
        if response is None or not response.is_success:
            return
        accounts = response.json()
        now = time.monotonic()
        watch_untils = [
            parsed for item in accounts
            if item.get("status") != "connected"
            for parsed in [_parse_watch_until(item.get("login_watch_until"))]
            if parsed and parsed > datetime.now(UTC)
        ]
        self._account_watch_until = max(watch_untils, default=None)
        found = {"claude": False, "codex": False}
        for account in accounts:
            config_dir = account.get("config_dir")
            kind = account.get("kind")
            engine = _engine_for_kind(kind)
            if engine is None:
                continue
            found[engine] = True
            profile_path = Path(config_dir).expanduser().resolve() if config_dir else None
            if profile_path is None or profile_path not in self._active_profile_dirs:
                _ensure_profile_dir(config_dir, kind)
            account_id = str(account.get("id", ""))
            watch = _parse_watch_until(account.get("login_watch_until"))
            interval = 5 if watch and watch > datetime.now(UTC) else 60
            if now - self._account_last_checks.get(account_id, 0) < interval:
                continue
            status, identity = _cli_identity(kind, Path(config_dir).expanduser() if config_dir else None)
            self._account_last_checks[account_id] = now
            credential_name = ".credentials.json" if engine == "claude" else "auth.json"
            # A missing CLI is not an account error. Preserve the safe, old file-presence
            # signal so a machine can still report an already completed login.
            ready = status == "connected" or (
                status == "unavailable" and config_dir
                and (Path(config_dir).expanduser() / credential_name).is_file()
            )
            payload = {"status": "connected" if ready else "pending_login"}
            if identity is not None:
                payload["identity"] = identity
            await self._request(
                client, "POST", f"/api/v0/accounts/{account['id']}/status",
                headers=self.headers, json=payload,
            )
        found_logins = []
        for engine, present in found.items():
            if present:
                continue
            base = Path.home() / (".claude" if engine == "claude" else ".codex")
            credential = ".credentials.json" if engine == "claude" else "auth.json"
            if (base / credential).is_file():
                _, identity = _found_cli_identity(engine)
                found_logins.append({"engine": engine, "identity": identity})
        await self._request(
            client, "POST", f"/api/v0/workers/{self.worker_id}/found-logins",
            headers=self.headers, json={"logins": found_logins},
        )
        self._last_account_check = time.monotonic()

    def _account_watch_active(self) -> bool:
        """The next heartbeat should be short while any login is being completed."""
        until = getattr(self, "_account_watch_until", None)
        if isinstance(until, datetime):
            return until > datetime.now(UTC)
        return bool(until)

    async def stop(self) -> None:
        adapters = tuple(self._active_adapters)
        if adapters:
            await asyncio.gather(*(adapter.interrupt() for adapter in adapters), return_exceptions=True)

    async def run(self) -> None:
        await asyncio.to_thread(
            _migrate_existing_profiles,
            None,
            allow_legacy_migration=os.environ.get("AIHUB_MIGRATE_LEGACY_PROFILES") == "1",
        )
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
            if request.get("kind") == "account_adopt_login":
                result = await asyncio.to_thread(_adopt_found_login, request)
                account_id = result["account_id"]
                await self._check_one_account_status(client, account_id)
            elif request.get("kind") == "account_delete":
                result = await asyncio.to_thread(_delete_account_profile, request)
            elif request.get("kind") == "git_merge":
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

    async def _check_one_account_status(self, client: httpx.AsyncClient, account_id: str) -> None:
        response = await self._request(
            client, "GET", f"/api/v0/accounts/{account_id}", headers=self.headers
        )
        if response is None or not response.is_success:
            return
        account = response.json()
        kind = account.get("kind")
        config_value = account.get("config_dir")
        if not config_value:
            return
        config_dir = Path(str(config_value)).expanduser()
        status, identity = _cli_identity(kind, config_dir)
        payload = {"status": "connected" if status == "connected" else "pending_login"}
        if identity is not None:
            payload["identity"] = identity
        await self._request(
            client, "POST", f"/api/v0/accounts/{account_id}/status",
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
        # A continuation in place brings only the files of its own message; a first run — all of the session's.
        new_files = (initial_event or {}).get("payload", {}).get("attachment_ids") if resuming else None
        attachment_links = (
            await self._download_attachments(client, session, assignment["id"], new_files, workdir)
            if not resuming or new_files else []
        )
        if attachment_links:
            prompt += "\n\nПользователь приложил файлы:\n" + "\n".join(attachment_links)
        config_dir = None
        active_profile: Path | None = None
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
            active_profile = Path(config_dir).expanduser().resolve() if config_dir else None
            if active_profile is not None:
                # Account status polling runs in the background. Never rename or
                # copy a profile while its native CLI session may hold files open.
                self._active_profile_dirs.add(active_profile)
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
        if engine == "claude_code" and continuation_ref and not compact and config_dir:
            # A session continued on another account: isolated profiles do not share projects/.
            bring_claude_transcript(Path(config_dir).expanduser(), continuation_ref)
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
                        ORCHESTRATOR_TOOLS
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
        # An executor's work is committed BEFORE its final status reaches the hub: the orchestrator reacts to
        # «completed» at once (orch_wait) and must find the commit on the branch, not uncommitted files.
        commit_state = {"done": False}
        executor = session.get("role") == "executor" and bool(session.get("orchestration"))

        async def commit_before_finish(index: int) -> None:
            if executor and not commit_state["done"]:
                commit_state["done"] = True
                await self._commit_executor_work(client, session, assignment["id"], workdir, index)

        event_task = asyncio.create_task(
            self._forward_events(client, session["id"], assignment["id"], adapter, commit_before_finish)
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
            # The adapter ended without a final status (a crash): still commit what the executor wrote.
            await commit_before_finish(self._worker_index(assignment["id"]))
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
                self._worker_index(assignment["id"]),
                {
                    "kind": "session.status",
                    "source": "heartbeat",
                    "payload": {"status": "failed", "reason": str(exc)[:500]},
                },
            )
        finally:
            self._active_adapters.discard(adapter)
            self._active_sessions.discard(session["id"])
            if active_profile is not None:
                self._active_profile_dirs.discard(active_profile)
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

    def _worker_index(self, assignment_id: str) -> int:
        """Indexes for the worker's own events (failures, commit notes), apart from the agent's 0, 1, 2…: a shared
        index made the hub drop the later event as a duplicate (a timeout after any agent output was lost)."""
        self._worker_seq[assignment_id] = self._worker_seq.get(assignment_id, 10**9) + 1
        return self._worker_seq[assignment_id]

    async def _fail(self, client: httpx.AsyncClient, session_id: str, assignment_id: str, reason: str) -> None:
        await self._post_event(
            client, session_id, assignment_id, self._worker_index(assignment_id),
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
        self, client: httpx.AsyncClient, session_id: str, assignment_id: str, adapter, before_finish=None
    ) -> None:
        index = 0
        async for event in adapter.start():
            if before_finish and event.kind == "session.status" and event.payload.get("status") in {"completed", "failed"}:
                await before_finish(index)  # its own event index: a shared one made the hub drop it as a duplicate
                index += 1
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


# Pre-approved for an orchestrator (non-interactive Claude silently denies anything that would need a prompt):
# it reviews and merges executor branches, runs the tests, and researches the task on the web. Found live:
# without WebSearch/WebFetch here it reported «web tools are unavailable» and fell back to the repository.
ORCHESTRATOR_TOOLS = ["mcp__knowledge", "Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebSearch", "WebFetch"]

DNS_FAILURES = ("name resolution", "name or service not known", "nodename nor servname", "no address associated")


def describe_hub_error(exc: Exception, hub_url: str) -> str:
    """A one-line, actionable reason why a request to the hub failed (no secrets: URLs only)."""
    host = urlparse(hub_url).hostname or hub_url
    text = " ".join(str(item) for item in (exc, exc.__cause__, exc.__context__) if item).lower()
    if isinstance(exc, httpx.HTTPStatusError):
        return f"the hub answered {exc.response.status_code} ({hub_url})"
    if any(marker in text for marker in DNS_FAILURES):
        return (f"cannot resolve {host}: DNS on this machine does not answer for it "
                f"(check: getent hosts {host}; in WSL see docs/workers.md, 'Worker is offline')")
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        return f"{host} does not answer in time (network or VPN; check: curl -sS {hub_url}/api/v0/health)"
    if "certificate" in text or "ssl" in text:
        return f"TLS error with {host}: {str(exc)[:160]}"
    if "refused" in text:
        return f"connection to {hub_url} refused (is the hub running? is the port right?)"
    return f"{type(exc).__name__} talking to {hub_url}: {str(exc)[:160]}"

def _ensure_profile_dir(config_dir: str | None, kind: str | None = None) -> None:
    """Create and prepare an account profile, without opening credential files."""
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
        if kind == "claude_code_subscription":
            _build_claude_overlay(
                resolved,
                Path.home() / ".claude",
                allow_legacy_migration=os.environ.get("AIHUB_MIGRATE_LEGACY_PROFILES") == "1",
            )
        elif kind == "codex_subscription":
            _ensure_codex_profile_overlay(
                resolved,
                Path.home() / ".codex",
                allow_legacy_migration=os.environ.get("AIHUB_MIGRATE_LEGACY_PROFILES") == "1",
            )
    except OSError:
        return


def _codex_base_home(config_dir: str | None) -> Path:
    return Path(config_dir or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def _build_codex_overlay(overlay: Path, base: Path, mcp_toml: str) -> None:
    """Link every entry of the base Codex profile except config.toml, which gains the session MCP servers."""
    # Session setup must never turn an existing profile's real sessions/ into a
    # symlink.  The explicit migration command is the only caller allowed to
    # do that.
    _ensure_codex_profile_overlay(base, Path.home() / ".codex")
    overlay.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.is_dir():
        for entry in base.iterdir():
            if entry.name != "config.toml":
                (overlay / entry.name).symlink_to(entry)
    base_config = base / "config.toml"
    prefix = base_config.read_text(encoding="utf-8") if base_config.is_file() else ""
    (overlay / "config.toml").write_text(prefix.rstrip("\n") + "\n\n" + mcp_toml, encoding="utf-8")


def _ensure_codex_profile_overlay(
    profile: Path,
    shared: Path,
    *,
    allow_legacy_migration: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Keep Codex rollout history shared while keeping auth.json in *profile*."""
    entries = {entry.name for entry in profile.iterdir()} if profile.is_dir() else set()
    legacy_sessions = (profile / "sessions").is_dir() and not (profile / "sessions").is_symlink()
    legacy = bool(entries - {"auth.json"})
    if legacy and not allow_legacy_migration:
        return []
    actions: list[str] = []
    if dry_run:
        if legacy_sessions:
            print("sessions-link: sessions -> ~/.codex/sessions")
        return ["sessions-link"] if legacy_sessions else []
    shared.mkdir(mode=0o700, parents=True, exist_ok=True)
    (shared / "sessions").mkdir(mode=0o700, exist_ok=True)
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    if profile.resolve() == shared.resolve():
        return actions
    sessions = profile / "sessions"
    if sessions.is_symlink():
        if sessions.resolve() == (shared / "sessions").resolve():
            return
        sessions.unlink()
    elif sessions.exists():
        try:
            _merge_shared_directory(sessions, shared / "sessions")
        except OSError:
            sessions.rename(_unique_backup_name(profile, "sessions"))
    if not sessions.exists() and not sessions.is_symlink():
        sessions.symlink_to(shared / "sessions")
        actions.append("sessions-link")
    return actions


_SESSION_REF = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def bring_claude_transcript(config_dir: Path, ref: str, home: Path | None = None) -> bool:
    """Copy a Claude conversation into `config_dir` when it lives only in another profile.

    Profiles with a shared projects/ already see it. The owner's isolated profiles do not, and `--resume`
    under the other account would answer «No conversation found». Copies, never moves: the source keeps
    its history. Returns whether a copy was made.
    """
    if not _SESSION_REF.match(ref):
        return False
    target = config_dir / "projects"
    if any(target.glob(f"*/{ref}.jsonl")):
        return False
    home = home or Path.home()
    roots = [home / ".claude" / "projects", *sorted((home / ".aihub" / "accounts").glob("*/claude/projects"))]
    for projects in roots:
        if projects.resolve() == target.resolve():
            continue
        for source in projects.glob(f"*/{ref}.jsonl"):
            dest = target / source.parent.name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / source.name)
            extra = source.with_suffix("")  # subagent transcripts of the same session
            if extra.is_dir() and not (dest / extra.name).exists():
                shutil.copytree(extra, dest / extra.name, symlinks=True)
            return True
    return False


_OVERLAY_MARKER = ".aihub-overlay.json"
# Claude creates these alongside its login/config files while running.  They
# belong to the profile, just like the login files, and must not be shared.
_CLAUDE_LOCAL_FILES = {".credentials.json", ".claude.json", ".claude.json.lock", "backups"}
# Only these Claude Code state/config entries are safe to share.  In
# particular, this is deliberately not a suffix-based allowlist: a profile
# may contain a different tool's live database (for example CODEX_HOME).
_CLAUDE_SHARED_ENTRIES = {
    "settings.json", "settings.local.json", "CLAUDE.md", "plugins", "skills",
    "agents", "commands", "projects", "sessions", "todos", "history.jsonl",
    "shell-snapshots", "session-env", "statsig", "ide",
    "plans", "hooks", "output-styles", "mcp-needs-auth-cache.json", "cache",
    "downloads", "file-history", "debug", "paste-cache", ".last-cleanup",
}


def _engine_for_kind(kind: str | None) -> str | None:
    return {"claude_code_subscription": "claude", "codex_subscription": "codex"}.get(kind)


def _parse_watch_until(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _cli_identity(kind: str | None, config_dir: Path | None) -> tuple[str, str | None]:
    """Return (connected/unavailable/pending, safe identity), never credential contents."""
    if config_dir is None:
        return "pending", None
    if kind == "claude_code_subscription":
        command, env_key = ["claude", "auth", "status", "--json"], "CLAUDE_CONFIG_DIR"
    elif kind == "codex_subscription":
        command, env_key = ["codex", "login", "status"], "CODEX_HOME"
    else:
        return "pending", None
    if kind == "codex_subscription":
        try:
            config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            return "unavailable", None
    try:
        result = subprocess.run(
            command, env={**os.environ, env_key: str(config_dir)},
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable", None
    if result.returncode != 0:
        return "pending", None
    if kind == "claude_code_subscription":
        try:
            value = json.loads(result.stdout)
        except (TypeError, ValueError):
            return "pending", None
        if not isinstance(value, dict) or value.get("loggedIn") is not True:
            return "pending", None
        identity = _json_identity(value)
    else:
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        identity = next((line[:200] for line in lines if "logged in" in line.lower() or "@" in line), None)
    return "connected", identity


def _found_cli_identity(engine: str) -> tuple[str, str | None]:
    """Check the machine-wide login without selecting an account profile."""
    if engine == "claude":
        command, env_key = ["claude", "auth", "status", "--json"], "CLAUDE_CONFIG_DIR"
        env = dict(os.environ)
        env.pop(env_key, None)
    elif engine == "codex":
        command, env_key = ["codex", "login", "status"], "CODEX_HOME"
        env = {**os.environ, env_key: str(Path.home() / ".codex")}
    else:
        return "pending", None
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable", None
    if result.returncode != 0:
        return "pending", None
    if engine == "claude":
        try:
            value = json.loads(result.stdout)
        except (TypeError, ValueError):
            return "pending", None
        if not isinstance(value, dict) or value.get("loggedIn") is not True:
            return "pending", None
        return "connected", _json_identity(value)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    identity = next((line[:200] for line in lines if "logged in" in line.lower() or "@" in line), None)
    return "connected", identity


def _migrate_existing_profiles(
    home: Path | None = None,
    *,
    allow_legacy_migration: bool = False,
) -> None:
    """Migrate only with explicit permission; otherwise record legacy names."""
    root_home = (home or Path.home()).expanduser()
    accounts = root_home / ".aihub" / "accounts"
    if not accounts.is_dir():
        return
    journal = root_home / ".aihub" / "migration.log"
    journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for account in sorted(accounts.iterdir(), key=lambda item: item.name):
        if not account.is_dir() or account.is_symlink():
            continue
        for engine in ("claude", "codex"):
            profile = account / engine
            if not profile.is_dir() or profile.is_symlink():
                continue
            key = f"{account.name}/{engine}"
            if engine == "claude":
                legacy = not (profile / _OVERLAY_MARKER).exists() and any(
                    entry.name not in _CLAUDE_LOCAL_FILES
                    and not entry.name.startswith(".aihub-overlay")
                    and not entry.is_symlink()
                    for entry in profile.iterdir()
                )
            else:
                legacy = any(entry.name != "auth.json" for entry in profile.iterdir())
            try:
                if engine == "claude":
                    actions = _build_claude_overlay(
                        profile,
                        root_home / ".claude",
                        allow_legacy_migration=allow_legacy_migration,
                    )
                else:
                    actions = _ensure_codex_profile_overlay(
                        profile,
                        root_home / ".codex",
                        allow_legacy_migration=allow_legacy_migration,
                    )
                if not allow_legacy_migration and legacy:
                    with journal.open("a", encoding="utf-8") as stream:
                        stream.write(f"legacy profile {key} not migrated; run migrate_profiles --dry-run\n")
                    continue
                if not legacy:
                    continue
                with journal.open("a", encoding="utf-8") as stream:
                    stream.write(f"{key}: completed ({len(actions)} actions)\n")
            except OSError as exc:
                # Do not include exception text: paths can contain user data.
                with journal.open("a", encoding="utf-8") as stream:
                    stream.write(f"{key}: deferred ({type(exc).__name__})\n")


def _json_identity(value: dict[str, Any]) -> str | None:
    for key in ("email", "orgName"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()[:200]
    return None


def _build_claude_overlay(
    profile: Path,
    base: Path,
    *,
    dry_run: bool = False,
    virtual_base: set[str] | None = None,
    allow_legacy_migration: bool = False,
) -> list[str]:
    """Plan and optionally apply one Claude overlay migration.

    The planner only inspects names, types and existence. Login files are never
    copied, opened, moved, renamed or linked; this is important while Claude
    may still have them open.
    """
    actions: list[tuple[str, Path, Path | None]] = []
    base_dirs = [base / "projects", base / "sessions"]
    link_names: set[str] = set()
    migrating_names: set[str] = set()
    # These roots are always ensured below, so link them during the same run
    # instead of making a second invocation appear to have work to do.
    link_names.update({"projects", "sessions"})
    virtual = virtual_base

    def relative(path: Path) -> str:
        return path.relative_to(base).as_posix()

    def occupied(path: Path) -> bool:
        return path.exists() or path.is_symlink() or (virtual is not None and relative(path) in virtual)

    def virtual_add_tree(path: Path, source: Path | None = None) -> None:
        if virtual is None:
            return
        virtual.add(relative(path))
        if source is not None and source.is_dir() and not source.is_symlink():
            for child in source.rglob("*"):
                virtual.add(relative(path) + "/" + child.relative_to(source).as_posix())
        elif path.is_dir() and not path.is_symlink():
            for child in path.rglob("*"):
                virtual.add(relative(child))

    if virtual is not None and not virtual:
        for path in base.rglob("*") if base.exists() else ():
            virtual.add(relative(path))

    def add(kind: str, source: Path, destination: Path | None = None) -> None:
        actions.append((kind, source, destination))

    def plan_merge(source: Path, destination: Path) -> bool:
        has_conflict = False
        for child in source.iterdir():
            target = destination / child.name
            target_is_dir = target.is_dir() or (
                virtual is not None
                and any(item.startswith(relative(target) + "/") for item in virtual)
            )
            if child.is_dir() and not child.is_symlink() and occupied(target) and target_is_dir:
                if relative(target).startswith("projects/"):
                    add("merge", child, target)
                has_conflict = plan_merge(child, target) or has_conflict
            elif occupied(target):
                has_conflict = True
                add("backup-entry", child, _unique_backup_name(source, child.name))
            else:
                add("move", child, target)
                virtual_add_tree(target, child)
        if not has_conflict:
            add("remove-empty", source)
        # A conflicting directory is left in place so the caller can rename
        # the top-level projects/sessions root as one recoverable unit.
        return has_conflict

    add("ensure-dir", base)
    for directory in base_dirs:
        add("ensure-dir", directory)
    marker = profile / _OVERLAY_MARKER
    if not marker.exists():
        legacy_entries = [
            entry for entry in profile.iterdir()
            if entry.name not in _CLAUDE_LOCAL_FILES
            and not entry.name.startswith(".aihub-overlay")
            and not entry.is_symlink()
        ]
        if legacy_entries and not allow_legacy_migration:
            return []
        if legacy_entries:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = profile.parent / f"{profile.name}.backup-{timestamp}"
            suffix = 2
            while backup.exists():
                backup = profile.parent / f"{profile.name}.backup-{timestamp}-{suffix}"
                suffix += 1
            add("backup-profile", profile, backup)
            for entry in legacy_entries:
                if entry.name not in _CLAUDE_SHARED_ENTRIES:
                    add("keep-unknown", entry)
                    continue
                link_names.add(entry.name)
                migrating_names.add(entry.name)
                destination = base / entry.name
                if entry.name in {"projects", "sessions"} and entry.is_dir():
                    if plan_merge(entry, destination):
                        add("backup-entry", entry, _unique_backup_name(profile, entry.name))
                elif occupied(destination):
                    add("backup-entry", entry, _unique_backup_name(profile, entry.name))
                else:
                    add("move", entry, destination)
                    virtual_add_tree(destination, entry)
            add("write-marker", marker)
    # Also repairs links if a prior run left a marker but was interrupted.
    for entry in base.iterdir() if base.exists() else ():
        if entry.name in _CLAUDE_LOCAL_FILES or entry.name not in _CLAUDE_SHARED_ENTRIES:
            continue
        link_names.add(entry.name)
    if virtual is not None:
        link_names.update(
            path.split("/", 1)[0] for path in virtual
            if path.split("/", 1)[0] in _CLAUDE_SHARED_ENTRIES
        )
    for name in sorted(link_names):
        entry = base / name
        target = profile / entry.name
        if name in migrating_names or (not target.exists() and not target.is_symlink()):
            add("symlink", entry, target)

    if dry_run:
        for kind, source, destination in actions:
            if kind == "backup-profile":
                print(f"backup: {destination} (non-login elements only)")
            elif kind == "backup-entry":
                print(f"profile-backup: {source.relative_to(profile)} -> {destination}")
            elif kind == "move":
                print(f"move: {source.name} -> {destination}")
            elif kind == "merge":
                print(f"merge: {source.relative_to(profile)}")
            elif kind == "keep-unknown":
                print(f"keep (unknown): {source.name}")
            elif kind == "symlink":
                print(f"symlink: {destination} -> {source}")
            elif kind == "write-marker":
                print(f"marker: {source.name}")
        return [kind for kind, _, _ in actions]

    for kind, source, destination in actions:
        if kind == "ensure-dir":
            source.mkdir(mode=0o700, parents=True, exist_ok=True)
        elif kind == "backup-profile":
            assert destination is not None
            shutil.copytree(
                source, destination, symlinks=True, dirs_exist_ok=False,
                ignore=lambda path, names: [
                    name for name in names
                    if Path(path) == profile and (name in _CLAUDE_LOCAL_FILES or name == _OVERLAY_MARKER)
                ],
            )
        elif kind == "move":
            assert destination is not None
            shutil.move(str(source), str(destination))
        elif kind == "backup-entry":
            assert destination is not None
            source.rename(destination)
        elif kind == "remove-empty":
            source.rmdir()
        elif kind == "write-marker":
            source.write_text(json.dumps({"version": 1, "migrated_at": datetime.now(UTC).isoformat()}), encoding="utf-8")
            source.chmod(0o600)
        elif kind == "symlink":
            assert destination is not None
            if not destination.exists() and not destination.is_symlink():
                destination.symlink_to(source)
    return [kind for kind, _, _ in actions]


def _merge_shared_directory(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = destination / entry.name
        if entry.is_dir() and not entry.is_symlink() and target.is_dir() and not target.is_symlink():
            _merge_shared_directory(entry, target)
        elif not target.exists() and not target.is_symlink():
            shutil.move(str(entry), str(target))
        else:
            entry.rename(_unique_backup_name(source, entry.name))
    try:
        source.rmdir()
    except OSError:
        pass


def _unique_backup_name(parent: Path, name: str) -> Path:
    candidate = parent / f"{name}.profile-backup"
    index = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = parent / f"{name}.profile-backup-{index}"
        index += 1
    return candidate


def _profile_path(account_id: str, engine: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", account_id):
        raise ValueError("invalid account id")
    if engine not in {"claude", "codex"}:
        raise ValueError("invalid engine")
    root = (Path.home() / ".aihub" / "accounts").resolve()
    path = (root / account_id / engine).resolve()
    if root not in path.parents:
        raise ValueError("profile path escapes accounts root")
    return path


def _adopt_found_login(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("response") or {}
    account_id = str(params.get("account_id") or request.get("path") or "")
    engine = str(params.get("engine") or "")
    profile = _profile_path(account_id, engine)
    source = Path.home() / (".claude" if engine == "claude" else ".codex")
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    copied = []
    if engine == "claude":
        sources = [(".credentials.json", source / ".credentials.json", True)]
        claude_json = source / ".claude.json"
        if not claude_json.is_file():
            claude_json = Path.home() / ".claude.json"
        sources.append((".claude.json", claude_json, False))
    else:
        sources = [("auth.json", source / "auth.json", True)]
    for name, source_file, required in sources:
        if not source_file.is_file():
            if not required:
                continue
            raise FileNotFoundError(f"source login file is missing: {source_file}")
        target = profile / name
        shutil.copyfile(source_file, target)
        target.chmod(0o600)
        copied.append(name)
    if engine == "claude":
        _build_claude_overlay(profile, source)
    else:
        (source / "sessions").mkdir(mode=0o700, parents=True, exist_ok=True)
    return {"account_id": account_id, "copied": copied}


def _delete_account_profile(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("response") or {}
    account_id = str(params.get("account_id") or request.get("path") or "")
    engine = str(params.get("engine") or "claude")
    _profile_path(account_id, engine)
    account_root = (Path.home() / ".aihub" / "accounts").resolve()
    account_dir = (account_root / account_id).resolve()
    if account_root not in account_dir.parents or account_dir == account_root:
        raise ValueError("invalid account path")
    if account_dir.exists():
        shutil.rmtree(account_dir)
    return {"deleted": True}


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
