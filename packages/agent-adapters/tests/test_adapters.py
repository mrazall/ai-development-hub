import os
import asyncio
import json
from pathlib import Path

import pytest

from aihub_agents.adapters import (
    ClaudeCodeAdapter,
    CodexExecAdapter,
    MockAdapter,
    _JsonLinesAdapter,
    context_tokens_from_usage,
    ensure_allowed_workdir,
    extract_claude_metadata,
    map_events,
    safe_path,
)
from aihub_agents.rate_limits import latest_codex_rollout_rate_limits
from aihub_agents.worker import should_compact_claude


async def _collect(adapter):
    return [event async for event in adapter.start()]


def test_mock_success_is_deterministic():
    events = asyncio.run(_collect(MockAdapter("success")))
    assert [event.kind for event in events] == ["session.status", "message", "session.status"]
    assert events[-1].payload["status"] == "completed"


def test_mock_echo_delivers_user_message():
    async def run():
        adapter = MockAdapter("echo")
        stream = adapter.start()
        assert (await anext(stream)).payload["status"] == "running"
        await adapter.send("hello from GUI")
        assert (await anext(stream)).payload == {"role": "assistant", "text": "echo: hello from GUI"}
        assert (await anext(stream)).payload["status"] == "completed"

    asyncio.run(run())


def test_workdir_and_file_gateway_reject_escape(tmp_path):
    root = ensure_allowed_workdir(str(tmp_path), [str(tmp_path)])
    with pytest.raises(ValueError):
        safe_path(root, "../outside")
    link = tmp_path / "link"
    link.symlink_to(tmp_path.parent)
    with pytest.raises(ValueError):
        safe_path(root, "link")


def test_workdir_allowlist_rejects_unapproved(tmp_path):
    with pytest.raises(ValueError):
        ensure_allowed_workdir(str(tmp_path), [str(tmp_path / "approved")])


def test_codex_command_is_workspace_scoped_and_contains_prompt(tmp_path):
    adapter = CodexExecAdapter("/profile", tmp_path, "gpt-test", "Fix the tests")
    assert adapter.command == [
        "codex", "exec", "--json", "--cd", str(tmp_path), "--sandbox", "workspace-write",
        "--skip-git-repo-check", "-m", "gpt-test", "--", "Fix the tests",
    ]
    assert adapter.workdir == str(tmp_path)
    assert "danger-full-access" not in adapter.command


def test_claude_command_is_workspace_scoped_and_uses_accept_edits(tmp_path):
    adapter = ClaudeCodeAdapter("/profile", tmp_path, "sonnet", "Update README")
    assert adapter.command == [
            "claude", "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--permission-mode", "acceptEdits", "--effort", "low", "--model", "sonnet", "--", "Update README",
    ]
    assert adapter.workdir == str(tmp_path)
    assert "--dangerously-skip-permissions" not in adapter.command


def test_claude_chat_command_uses_session_mcp_without_token_in_argv(tmp_path):
    adapter = ClaudeCodeAdapter(
        "/profile", tmp_path, "sonnet", "Remember this",
        mcp_config="/tmp/aihub-mcp/mcp.json",
        append_system_prompt="search memory first",
        allowed_tools=["mcp__knowledge"],
        extra_env={"AIHUB_HUB_TOKEN": "scoped-secret"},
    )
    assert adapter.command[adapter.command.index("--mcp-config") + 1] == "/tmp/aihub-mcp/mcp.json"
    assert "mcp__knowledge" in adapter.command
    assert "scoped-secret" not in adapter.command
    assert adapter.extra_env["AIHUB_HUB_TOKEN"] == "scoped-secret"


def test_prompts_are_never_parsed_as_flags():
    from aihub_agents.adapters import ClaudeCodeAdapter, CodexExecAdapter

    for adapter in (ClaudeCodeAdapter(prompt="--dangerously-skip-permissions"), CodexExecAdapter(prompt="--sandbox=danger-full-access")):
        argv = adapter.command
        assert argv[-2:] == ["--", argv[-1]] and argv[-1].startswith("--")
        assert "--dangerously-skip-permissions" not in argv[:-1]
        assert "danger-full-access" not in " ".join(argv[:-1])


def test_one_shot_cli_adapters_do_not_accept_runtime_input():
    for adapter in (ClaudeCodeAdapter(), CodexExecAdapter()):
        assert adapter.accepts_input is False
        with pytest.raises(RuntimeError, match="does not accept messages"):
            asyncio.run(adapter.send("message"))


def test_json_lines_adapter_can_use_devnull_stdin():
    adapter = _JsonLinesAdapter(["/bin/true"], "TEST", accepts_input=False)
    assert adapter.accepts_input is False


def test_recorded_codex_jsonl_maps_to_contract_events():
    fixture = Path(__file__).parent / "fixtures" / "codex-session.jsonl"
    events = [event for line in fixture.read_text().splitlines() for event in map_events(json.loads(line))]
    assert [event.kind for event in events] == [
        "tool.call", "tool.result", "tool.call", "tool.result", "diff", "message", "message", "message", "message"
    ]
    assert events[1].payload["output"] == "hello\n"
    assert events[1].payload["raw_type"] == "item.completed"
    assert events[4].payload["changes"] == [{"path": "README.md", "kind": "modified"}]
    assert events[5].payload["text"] == "Готово"
    assert events[6].payload["usage"]["output_tokens"] == 17


def test_tool_output_is_bounded():
    event = map_events({
        "type": "item.completed",
        "item": {"type": "command_execution", "aggregated_output": "x" * 9000, "exit_code": 0},
    })[0]
    assert len(event.payload["output"]) == 8192


def test_json_lines_status_walks_the_state_machine():
    # The hub rejects starting -> completed; a real Codex run must report running first.
    fixture = Path(__file__).parent / "fixtures" / "codex-session.jsonl"
    events = asyncio.run(_collect(_JsonLinesAdapter(["cat", str(fixture)], "TEST", accepts_input=False)))
    statuses = [event.payload["status"] for event in events if event.kind == "session.status"]
    assert statuses == ["running", "completed"]


def test_json_lines_nonzero_exit_fails_after_running():
    events = asyncio.run(_collect(_JsonLinesAdapter(["false"], "TEST", accepts_input=False)))
    statuses = [event.payload["status"] for event in events if event.kind == "session.status"]
    assert statuses == ["running", "failed"]


def test_config_dir_tilde_is_expanded(tmp_path, monkeypatch):
    # Account profiles are stored as ~/.aihub/accounts/<id>/...; the CLI must get a real path.
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = _JsonLinesAdapter(["sh", "-c", 'printf "%s\n" "$TEST"'], "TEST", "~/.aihub/x", accepts_input=False)
    events = asyncio.run(_collect(adapter))
    assert any(event.payload.get("text") == f"{tmp_path}/.aihub/x" for event in events)


def test_claude_stream_json_extracts_session_and_final_context_usage():
    records = [
        {"type": "system", "subtype": "init", "session_id": "claude-123"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
        {"type": "result", "session_id": "claude-123", "usage": {
            "input_tokens": 10, "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 30, "output_tokens": 7,
        }},
    ]
    assert extract_claude_metadata(records) == ("claude-123", 60)
    result = map_events(records[-1])[0]
    assert result.payload["engine_session_ref"] == "claude-123"
    assert result.payload["context_tokens"] == 60
    assert context_tokens_from_usage(records[-1]["usage"]) == 60


def test_claude_resume_is_before_prompt_separator(tmp_path):
    adapter = ClaudeCodeAdapter(
        "/profile", tmp_path, "sonnet", "--looks-like-a-flag", resume="claude-123"
    )
    assert adapter.command == [
            "claude", "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--permission-mode", "acceptEdits", "--effort", "low", "--model", "sonnet", "--resume", "claude-123",
        "--", "--looks-like-a-flag",
    ]


def test_compaction_selection_honors_threshold_and_fresh(monkeypatch):
    monkeypatch.setenv("AIHUB_CLAUDE_CONTEXT_LIMIT", "100")
    assert not should_compact_claude(99, False)
    assert should_compact_claude(100, False)
    assert should_compact_claude(None, True)


def test_codex_rollout_parser_uses_newest_session_file_only(tmp_path):
    old = tmp_path / "sessions" / "old"
    new = tmp_path / "sessions" / "new"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "rollout-old.jsonl").write_text('{"rate_limits":{"primary":{"used_percent":1}}}\n')
    newest = new / "rollout-new.jsonl"
    newest.write_text('{"noise":"ignored"}\n{"rate_limits":{"primary":{"used_percent":42,"resets_at":123},"secondary":{"used_percent":7}}}\n')
    import os
    result = latest_codex_rollout_rate_limits(tmp_path, os.path.getmtime(newest) - 1)
    assert result == [
        {"kind": "five_hour", "used_percent": 42.0, "resets_at": 123},
        {"kind": "seven_day", "used_percent": 7.0, "resets_at": None},
    ]


def test_claude_nested_tool_blocks_become_tool_events_not_empty_messages():
    assistant = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "mcp__knowledge__knowledge_search", "input": {"query": "VDS SSH", "limit": 5}},
    ]}}
    user = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "VDS.md ...", "is_error": False}]}}
    answer = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Порт 3333"}]}}
    events = [event for value in (assistant, user, answer) for event in map_events(value)]
    assert [event.kind for event in events] == ["tool.call", "tool.result", "message"]
    assert events[0].payload["summary"] == "VDS SSH"
    assert events[2].payload["text"] == "Порт 3333"


def test_profile_dir_is_created_only_under_aihub_accounts(tmp_path, monkeypatch):
    from aihub_agents.worker import _ensure_profile_dir

    monkeypatch.setenv("HOME", str(tmp_path))
    _ensure_profile_dir("~/.aihub/accounts/codex-main/codex")
    created = tmp_path / ".aihub/accounts/codex-main/codex"
    assert created.is_dir() and oct(created.stat().st_mode)[-3:] == "700"
    _ensure_profile_dir(str(tmp_path / "elsewhere"))
    assert not (tmp_path / "elsewhere").exists()


def test_chat_sessions_use_lean_tools_and_only_our_mcp(tmp_path):
    adapter = ClaudeCodeAdapter(workdir=tmp_path, prompt="hi", mcp_config=tmp_path / "mcp.json")
    command = adapter.command
    assert "--strict-mcp-config" in command and "--disable-slash-commands" in command
    assert command[command.index("--tools") + 1] == "Read Edit Write Bash Glob Grep WebFetch WebSearch"
    assert command[-2:] == ["--", "hi"]
    assert "--tools" not in ClaudeCodeAdapter(workdir=tmp_path, prompt="task").command


def test_codex_rollout_rate_limits_are_found_when_nested():
    from aihub_agents.rate_limits import parse_codex_rate_limits

    line = json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "primary": {"used_percent": 0.0, "window_minutes": 300, "resets_at": 1},
        "secondary": {"used_percent": 6.0, "window_minutes": 10080, "resets_at": 2}}}})
    assert parse_codex_rate_limits(line) == [
        {"kind": "five_hour", "used_percent": 0.0, "resets_at": 1},
        {"kind": "seven_day", "used_percent": 6.0, "resets_at": 2},
    ]


def test_executor_worktree_is_created_even_if_attachments_dir_exists(tmp_path):
    import subprocess

    from aihub_agents.workspace import prepare_worktree

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)
    target = repo / ".aihub" / "worktrees" / "exec-1"
    (target / ".aihub" / "attachments").mkdir(parents=True)  # created by attachment download first
    prepare_worktree(str(repo), str(target), "aihub/demo/1-part", "master")
    assert (target / ".git").exists()
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "aihub/demo/1-part"],
                              capture_output=True, text=True, check=True).stdout
    assert "aihub/demo/1-part" in branches


def test_claude_runs_at_low_effort_by_default(tmp_path):
    command = ClaudeCodeAdapter(workdir=tmp_path, prompt="hi").command
    assert command[command.index("--effort") + 1] == "low"


def test_codex_resume_command_and_thread_reference():
    from aihub_agents.adapters import CodexExecAdapter, claude_session_id

    adapter = CodexExecAdapter(None, "/w", "gpt-5.6-luna", "доделай", resume="thread-1")
    assert adapter.command[:3] == ["codex", "exec", "resume"]
    assert adapter.command[-2:] == ["thread-1", "доделай"] and "--cd" not in adapter.command
    assert claude_session_id({"type": "thread.started", "thread_id": "thread-1"}) == "thread-1"


def test_chat_command_can_reach_the_home_directory(tmp_path):
    from aihub_agents.adapters import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter(None, tmp_path, None, "hi", allowed_tools=["mcp__knowledge", "Bash"], add_dirs=["~"])
    index = adapter.command.index("--add-dir")
    assert adapter.command[index + 1] == os.path.expanduser("~")
    assert adapter.command[adapter.command.index("--allowedTools") + 2] == "Bash"


def test_claude_uses_the_effort_a_chat_chose(tmp_path):
    command = ClaudeCodeAdapter(workdir=tmp_path, prompt="hi", effort="high").command
    assert command[command.index("--effort") + 1] == "high"
