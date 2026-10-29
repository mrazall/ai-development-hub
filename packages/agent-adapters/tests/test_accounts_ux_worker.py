import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest


def test_claude_overlay_migrates_without_losing_login_or_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AIHUB_MIGRATE_LEGACY_PROFILES", "1")
    from aihub_agents.worker import _ensure_profile_dir

    profile = tmp_path / ".aihub/accounts/claude-1/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_text("secret", encoding="utf-8")
    (profile / ".claude.json").write_text("config", encoding="utf-8")
    (profile / "settings.json").write_text("settings", encoding="utf-8")
    (profile / "plugins").mkdir()
    (profile / "skills").mkdir()
    (profile / "projects").mkdir()
    (profile / "projects" / "cwd").mkdir()
    (profile / "projects" / "cwd" / "chat.jsonl").write_text("history", encoding="utf-8")
    (profile / "sessions").mkdir()
    (profile / "sessions" / "s.jsonl").write_text("session", encoding="utf-8")

    _ensure_profile_dir(str(profile), "claude_code_subscription")
    assert (profile / ".credentials.json").read_text() == "secret"
    assert (profile / ".claude.json").read_text() == "config"
    assert (tmp_path / ".claude/projects/cwd/chat.jsonl").read_text() == "history"
    assert (tmp_path / ".claude/sessions/s.jsonl").read_text() == "session"
    for name in ("settings.json", "plugins", "skills", "projects", "sessions"):
        assert (profile / name).is_symlink()
    assert (profile / ".aihub-overlay.json").is_file()
    assert list(profile.parent.glob("claude.backup-*"))
    before = sorted(str(path) for path in profile.parent.iterdir())
    _ensure_profile_dir(str(profile), "claude_code_subscription")
    assert sorted(str(path) for path in profile.parent.iterdir()) == before


def test_adopt_copies_only_login_files_and_delete_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _adopt_found_login, _delete_account_profile

    source = tmp_path / ".claude"
    source.mkdir()
    (source / ".credentials.json").write_text("credential", encoding="utf-8")
    (source / ".claude.json").write_text("claude", encoding="utf-8")
    (source / "settings.json").write_text("shared", encoding="utf-8")
    result = _adopt_found_login({"path": "claude-1", "response": {"account_id": "claude-1", "engine": "claude"}})
    profile = tmp_path / ".aihub/accounts/claude-1/claude"
    assert result["copied"] == [".credentials.json", ".claude.json"]
    assert (profile / ".credentials.json").stat().st_mode & 0o777 == 0o600
    assert (profile / "settings.json").is_symlink()
    with pytest.raises(ValueError):
        _delete_account_profile({"path": "../escape", "response": {"account_id": "../escape", "engine": "claude"}})
    escape = tmp_path / ".aihub/accounts/claude-2"
    escape.parent.mkdir(parents=True, exist_ok=True)
    escape.symlink_to(tmp_path)
    with pytest.raises(ValueError):
        _delete_account_profile({"path": "claude-2", "response": {"account_id": "claude-2", "engine": "claude"}})


def test_identity_parser_uses_official_commands_and_only_returns_identity(monkeypatch, tmp_path):
    from aihub_agents.worker import _cli_identity

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return subprocess.CompletedProcess(
            command, 0,
            '{"loggedIn":true,"email":"user@example.com","token":"secret",'
            '"nested":{"email":"wrong@example.com"}}', "",
        )

    monkeypatch.setattr("aihub_agents.worker.subprocess.run", fake_run)
    status, identity = _cli_identity("claude_code_subscription", tmp_path)
    assert (status, identity) == ("connected", "user@example.com")
    assert calls[0][0] == ["claude", "auth", "status", "--json"]
    assert calls[0][1]["CLAUDE_CONFIG_DIR"] == str(tmp_path)


def test_claude_status_requires_logged_in_and_does_not_search_nested_identity(monkeypatch, tmp_path):
    from aihub_agents.worker import _cli_identity

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, '{"loggedIn":false,"nested":{"email":"wrong@example.com"}}', "",
        )

    monkeypatch.setattr("aihub_agents.worker.subprocess.run", fake_run)
    assert _cli_identity("claude_code_subscription", tmp_path) == ("pending", None)


def test_codex_status_creates_missing_profile_home(monkeypatch, tmp_path):
    from aihub_agents.worker import _cli_identity

    codex_home = tmp_path / "missing-codex-home"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return subprocess.CompletedProcess(command, 1, "Not logged in", "")

    monkeypatch.setattr("aihub_agents.worker.subprocess.run", fake_run)
    assert _cli_identity("codex_subscription", codex_home) == ("pending", None)
    assert codex_home.is_dir()
    assert calls[0][1]["CODEX_HOME"] == str(codex_home)


def test_found_identity_uses_machine_cli_home_without_claude_profile(monkeypatch, tmp_path):
    from aihub_agents.worker import _found_cli_identity

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return subprocess.CompletedProcess(command, 0, '{"loggedIn":true,"email":"owner@example.com"}', "")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr("aihub_agents.worker.subprocess.run", fake_run)
    assert _found_cli_identity("claude") == ("connected", "owner@example.com")
    assert calls[0][0] == ["claude", "auth", "status", "--json"]
    assert "CLAUDE_CONFIG_DIR" not in calls[0][1]


def test_codex_profile_keeps_auth_private_and_links_shared_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _ensure_profile_dir

    profile = tmp_path / ".aihub/accounts/codex-1/codex"
    profile.mkdir(parents=True)
    (profile / "auth.json").write_text("private", encoding="utf-8")
    _ensure_profile_dir(str(profile), "codex_subscription")

    assert (profile / "auth.json").is_file()
    assert not (profile / "auth.json").is_symlink()
    assert (profile / "sessions").is_symlink()
    assert (profile / "sessions").resolve() == (tmp_path / ".codex/sessions").resolve()


def test_startup_migration_writes_name_only_journal_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _migrate_existing_profiles

    profile = tmp_path / ".aihub/accounts/claude-main/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_text("SECRET", encoding="utf-8")
    (profile / "settings.json").write_text("settings", encoding="utf-8")
    _migrate_existing_profiles()
    _migrate_existing_profiles()

    journal = (tmp_path / ".aihub/migration.log").read_text(encoding="utf-8")
    assert journal.count("legacy profile claude-main/claude not migrated; run migrate_profiles --dry-run") == 2
    assert "SECRET" not in journal
    assert (profile / ".credentials.json").read_text(encoding="utf-8") == "SECRET"


def test_claude_adopt_uses_actual_config_locations_and_allows_missing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _adopt_found_login

    source = tmp_path / ".claude"
    source.mkdir()
    (source / ".credentials.json").write_text("credential", encoding="utf-8")
    (source / ".claude.json").write_text("profile-config", encoding="utf-8")
    (tmp_path / ".claude.json").write_text("home-config", encoding="utf-8")
    result = _adopt_found_login({"path": "adopt-actual", "response": {"account_id": "adopt-actual", "engine": "claude"}})
    assert result["copied"] == [".credentials.json", ".claude.json"]
    profile = tmp_path / ".aihub/accounts/adopt-actual/claude"
    assert (profile / ".claude.json").read_text() == "profile-config"

    (source / ".claude.json").unlink()
    (tmp_path / ".claude.json").unlink()
    (tmp_path / ".claude.json").write_text("home-config", encoding="utf-8")
    result = _adopt_found_login({"path": "adopt-no-config", "response": {"account_id": "adopt-no-config", "engine": "claude"}})
    assert result["copied"] == [".credentials.json", ".claude.json"]
    assert (tmp_path / ".aihub/accounts/adopt-no-config/claude/.claude.json").read_text() == "home-config"

    (tmp_path / ".claude.json").unlink()
    result = _adopt_found_login({"path": "adopt-no-config-file", "response": {"account_id": "adopt-no-config-file", "engine": "claude"}})
    assert result["copied"] == [".credentials.json"]


def test_claude_service_files_stay_local_and_are_not_linked(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _ensure_profile_dir

    shared = tmp_path / ".claude"
    (shared / "backups").mkdir(parents=True)
    (shared / "backups" / "shared").write_text("shared", encoding="utf-8")
    (shared / ".claude.json.lock").write_text("shared-lock", encoding="utf-8")
    profile = tmp_path / ".aihub/accounts/local/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_text("credential", encoding="utf-8")
    (profile / ".claude.json.lock").write_text("local-lock", encoding="utf-8")
    (profile / "backups").mkdir()
    (profile / "backups" / "local").write_text("local", encoding="utf-8")

    _ensure_profile_dir(str(profile), "claude_code_subscription")

    assert (profile / ".claude.json.lock").read_text() == "local-lock"
    assert (profile / "backups" / "local").read_text() == "local"
    assert not (profile / ".claude.json.lock").is_symlink()
    assert not (profile / "backups").is_symlink()
    assert not (profile / "backups" / "shared").exists()


def test_install_cli_dry_run_is_non_mutating():
    script = Path(__file__).parents[1] / "scripts/install-cli.sh"
    result = subprocess.run([str(script), "codex", "--dry-run"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "npm i -g --prefix \"$HOME/.local\" @openai/codex" in result.stdout
    assert "npm config set prefix" not in result.stdout


def test_migration_preserves_login_bytes_and_backups_only_conflicts(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AIHUB_MIGRATE_LEGACY_PROFILES", "1")
    from aihub_agents.worker import _ensure_profile_dir

    shared = tmp_path / ".claude"
    (shared / "projects" / "p").mkdir(parents=True)
    (shared / "settings.json").write_bytes(b"shared-settings")
    (shared / "projects" / "p" / "other.jsonl").write_bytes(b"shared-history")
    (shared / "projects" / "p" / "same.jsonl").write_bytes(b"shared-version")
    profile = tmp_path / ".aihub/accounts/p1/claude"
    (profile / "projects" / "p").mkdir(parents=True)
    (profile / "settings.json").write_bytes(b"profile-settings")
    (profile / "projects" / "p" / "same.jsonl").write_bytes(b"profile-version")
    (profile / "projects" / "p" / "new.jsonl").write_bytes(b"profile-history")
    credentials = b"credential-bytes"
    claude_json = b"claude-json-bytes"
    (profile / ".credentials.json").write_bytes(credentials)
    (profile / ".claude.json").write_bytes(claude_json)
    for name in ("plugins", "skills", "sessions"):
        (profile / name).mkdir()
    (profile / "CLAUDE.md").write_bytes(b"instructions")

    _ensure_profile_dir(str(profile), "claude_code_subscription")

    assert (profile / ".credentials.json").read_bytes() == credentials
    assert (profile / ".claude.json").read_bytes() == claude_json
    assert (shared / "projects" / "p" / "other.jsonl").read_bytes() == b"shared-history"
    assert (shared / "projects" / "p" / "new.jsonl").read_bytes() == b"profile-history"
    assert (shared / "projects" / "p" / "same.jsonl").read_bytes() == b"shared-version"
    assert (profile / "projects.profile-backup" / "p" / "same.jsonl.profile-backup").read_bytes() == b"profile-version"
    assert (profile / "settings.json.profile-backup").read_bytes() == b"profile-settings"
    assert (shared / "CLAUDE.md").read_bytes() == b"instructions"
    assert list(profile.parent.glob("claude.backup-*"))
    assert (profile / ".aihub-overlay.json").is_file()
    assert all((profile / name).is_symlink() for name in (
        "settings.json", "plugins", "skills", "projects", "sessions", "CLAUDE.md",
    ))
    before = sorted(path.relative_to(profile.parent).as_posix() for path in profile.parent.rglob("*"))
    _ensure_profile_dir(str(profile), "claude_code_subscription")
    after = sorted(path.relative_to(profile.parent).as_posix() for path in profile.parent.rglob("*"))
    assert after == before
    assert len(list(profile.parent.glob("claude.backup-*"))) == 1


def test_migrate_profiles_dry_run_is_name_only_and_non_mutating(tmp_path):
    profile = tmp_path / ".aihub/accounts/claude-main/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_text("do-not-print", encoding="utf-8")
    (profile / ".claude.json").write_text("do-not-print-either", encoding="utf-8")
    (profile / "settings.json").write_text("settings", encoding="utf-8")
    (profile / "projects/session.jsonl").parent.mkdir()
    (profile / "projects/session.jsonl").write_text("history", encoding="utf-8")

    def tree():
        return sorted(
            (str(path.relative_to(tmp_path)), path.is_symlink(), path.stat().st_size if path.is_file() else None)
            for path in tmp_path.rglob("*")
        )

    before = tree()
    result = subprocess.run(
        [sys.executable, "-m", "aihub_agents.migrate_profiles", "--dry-run", "--home", str(tmp_path)],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert tree() == before
    assert "claude-main/claude" in result.stdout
    assert "settings.json" in result.stdout
    assert "projects" in result.stdout
    assert "do-not-print" not in result.stdout


def test_migrate_profiles_real_run_uses_worker_overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    profile = tmp_path / ".aihub/accounts/codex-main/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_text("credential", encoding="utf-8")
    (profile / "settings.json").write_text("settings", encoding="utf-8")

    from aihub_agents.migrate_profiles import migrate_profiles
    migrate_profiles(tmp_path, dry_run=False)

    assert (profile / ".credentials.json").read_text(encoding="utf-8") == "credential"
    assert (profile / "settings.json").is_symlink()
    assert (tmp_path / ".claude/settings.json").read_text(encoding="utf-8") == "settings"


def test_migrate_profiles_filters_codex_state_and_models_multiple_profiles(tmp_path):
    accounts = tmp_path / ".aihub/accounts"
    first = accounts / "claude-main/claude"
    second = accounts / "claude-second/claude"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "history.jsonl").write_text("first", encoding="utf-8")
    (first / "projects/shared/first.jsonl").parent.mkdir(parents=True)
    (first / "projects/shared/first.jsonl").write_text("first-project", encoding="utf-8")
    (second / "history.jsonl").write_text("second", encoding="utf-8")
    (second / "projects/shared/conflict.jsonl").parent.mkdir(parents=True)
    (second / "projects/shared/conflict.jsonl").write_text("second-project", encoding="utf-8")
    (tmp_path / ".claude/projects/shared/conflict.jsonl").parent.mkdir(parents=True)
    (tmp_path / ".claude/projects/shared/conflict.jsonl").write_text("existing", encoding="utf-8")

    codex_names = [
        "state_5.sqlite", "state_5.sqlite-shm", "state_5.sqlite-wal",
        "logs_2.sqlite", "logs_2.sqlite-shm", "logs_2.sqlite-wal",
        "memories_1.sqlite", "goals_1.sqlite", "queue_1.sqlite",
        "thread_history_1.sqlite", "config.toml", "installation_id",
        ".sandbox_migration", ".tmp", "tmp", "shell_snapshots", "thread-writer-locks",
    ]
    for name in codex_names:
        path = second / name
        if name in {"tmp", "thread-writer-locks"}:
            path.mkdir()
        else:
            path.write_text("codex", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "aihub_agents.migrate_profiles", "--dry-run", "--home", str(tmp_path)],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "move: history.jsonl" in result.stdout
    assert "profile-backup: history.jsonl" in result.stdout
    assert "merge: projects/shared" in result.stdout
    assert "profile-backup: projects/shared/conflict.jsonl" in result.stdout
    for name in codex_names:
        assert f"keep (unknown): {name}" in result.stdout
        assert not (tmp_path / ".claude" / name).exists()

    from aihub_agents.migrate_profiles import migrate_profiles
    migrate_profiles(tmp_path, dry_run=False)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    migrate_profiles(tmp_path, dry_run=False)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert after == before
    assert all((second / name).exists() for name in codex_names)
    assert not any((tmp_path / ".claude" / name).exists() for name in codex_names)
    assert (second / "history.jsonl.profile-backup").read_text(encoding="utf-8") == "second"


def test_new_claude_profile_has_only_login_files_and_shared_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _ensure_profile_dir

    shared = tmp_path / ".claude"
    shared.mkdir()
    (shared / "settings.json").write_text("settings", encoding="utf-8")
    for name in ("plugins", "skills", "projects", "sessions", "CLAUDE.md"):
        (shared / name).mkdir() if name != "CLAUDE.md" else (shared / name).write_text("shared", encoding="utf-8")
    profile = tmp_path / ".aihub/accounts/new/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_bytes(b"credentials")
    (profile / ".claude.json").write_bytes(b"claude")
    _ensure_profile_dir(str(profile), "claude_code_subscription")

    assert sorted(item.name for item in profile.iterdir()) == [
        ".claude.json", ".credentials.json", "CLAUDE.md", "plugins", "projects", "sessions",
        "settings.json", "skills",
    ]
    assert all(item.is_symlink() for item in profile.iterdir() if item.name not in {
        ".claude.json", ".credentials.json",
    })
    assert not list(profile.parent.glob("*.backup-*"))
    assert not (profile / ".aihub-overlay.json").exists()


def test_legacy_claude_profile_is_unchanged_without_migration_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _ensure_profile_dir

    profile = tmp_path / ".aihub/accounts/legacy/claude"
    profile.mkdir(parents=True)
    (profile / ".credentials.json").write_text("secret", encoding="utf-8")
    (profile / "settings.json").write_text("settings", encoding="utf-8")
    before = sorted((p.relative_to(profile).as_posix(), p.is_symlink(), p.read_bytes() if p.is_file() else None)
                    for p in profile.rglob("*"))

    _ensure_profile_dir(str(profile), "claude_code_subscription")

    after = sorted((p.relative_to(profile).as_posix(), p.is_symlink(), p.read_bytes() if p.is_file() else None)
                   for p in profile.rglob("*"))
    assert after == before
    assert not (profile / ".aihub-overlay.json").exists()


def test_legacy_codex_sessions_are_unchanged_without_migration_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _ensure_profile_dir

    profile = tmp_path / ".aihub/accounts/legacy/codex"
    (profile / "sessions").mkdir(parents=True)
    (profile / "sessions/rollout.jsonl").write_text("history", encoding="utf-8")
    (profile / "auth.json").write_text("auth", encoding="utf-8")
    before = sorted((p.relative_to(profile).as_posix(), p.is_symlink(), p.read_bytes() if p.is_file() else None)
                    for p in profile.rglob("*"))

    _ensure_profile_dir(str(profile), "codex_subscription")

    after = sorted((p.relative_to(profile).as_posix(), p.is_symlink(), p.read_bytes() if p.is_file() else None)
                   for p in profile.rglob("*"))
    assert after == before
    assert not (profile / "sessions").is_symlink()


@pytest.mark.parametrize("account_id", ["../escape", "/tmp/absolute", "Bad_ID"])
def test_delete_rejects_invalid_ids_without_deleting_outside(tmp_path, monkeypatch, account_id):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _delete_account_profile

    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        _delete_account_profile({"path": account_id, "response": {"engine": "claude"}})
    assert marker.read_text(encoding="utf-8") == "keep"


def test_delete_rejects_account_directory_symlink_and_deletes_normal_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _delete_account_profile

    root = tmp_path / ".aihub/accounts"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        _delete_account_profile({"path": "linked", "response": {"engine": "claude"}})
    assert (outside / "keep.txt").exists()
    normal = root / "normal" / "claude"
    normal.mkdir(parents=True)
    (normal / "file").write_text("delete", encoding="utf-8")
    assert _delete_account_profile({"path": "normal", "response": {"engine": "claude"}}) == {"deleted": True}
    assert not (root / "normal").exists()


def test_adopt_missing_source_is_clear_and_never_prints_login_content(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import _adopt_found_login

    source = tmp_path / ".claude"
    source.mkdir()
    with pytest.raises(FileNotFoundError, match="source login file is missing"):
        _adopt_found_login({"path": "adopt-1", "response": {"account_id": "adopt-1", "engine": "claude"}})
    assert "SECRET-CREDENTIAL" not in capsys.readouterr().out
    (source / ".credentials.json").write_text("SECRET-CREDENTIAL", encoding="utf-8")
    (source / ".claude.json").write_text("SECRET-CLAUDE", encoding="utf-8")
    _adopt_found_login({"path": "adopt-1", "response": {"account_id": "adopt-1", "engine": "claude"}})
    captured = capsys.readouterr()
    assert "SECRET-CREDENTIAL" not in captured.out
    assert "SECRET-CLAUDE" not in captured.out
    assert (tmp_path / ".aihub/accounts/adopt-1/claude/.credentials.json").stat().st_mode & 0o777 == 0o600


def test_login_watch_uses_five_second_interval_and_stops_after_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import Worker

    now = datetime.now(UTC)
    worker = Worker("http://control", "worker", "token")
    worker._account_watch_until = now + timedelta(seconds=30)
    worker._account_last_checks["a"] = 100.0
    monkeypatch.setattr("aihub_agents.worker.time.monotonic", lambda: 104.9)
    assert worker._account_watch_active()
    assert 104.9 - worker._account_last_checks["a"] < 5
    monkeypatch.setattr("aihub_agents.worker.time.monotonic", lambda: 105.0)
    assert 105.0 - worker._account_last_checks["a"] >= 5
    worker._account_watch_until = now - timedelta(seconds=1)
    assert not worker._account_watch_active()


def test_found_logins_only_reports_unprofiled_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import Worker

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/.credentials.json").write_text("secret", encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/auth.json").write_text("secret", encoding="utf-8")
    worker = Worker("http://control", "worker", "token")
    posted = []

    async def request(_client, method, path, **kwargs):
        if method == "GET":
            return type("Response", (), {"is_success": True, "json": lambda self: [
                {"id": "claude-1", "kind": "claude_code_subscription", "config_dir": str(tmp_path / ".aihub/accounts/claude-1/claude")},
            ]})()
        posted.append(kwargs["json"])
        return type("Response", (), {"is_success": True})()

    monkeypatch.setattr("aihub_agents.worker._cli_identity", lambda *_: ("pending", None))
    worker._request = request
    asyncio.run(worker.check_account_statuses(object()))
    assert posted[-1] == {"logins": [{"engine": "codex", "identity": None}]}


def test_service_workspace_request_posts_response_with_mock_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aihub_agents.worker import Worker

    seen = []
    monkeypatch.setattr("aihub_agents.worker._delete_account_profile", lambda request: {"deleted": True})

    async def direct(func, *args):
        return func(*args)

    monkeypatch.setattr("aihub_agents.worker.asyncio.to_thread", direct)

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/requests/next"):
            return httpx.Response(200, json={"id": "req-1", "kind": "account_delete", "path": "delete-me", "response": {"account_id": "delete-me", "engine": "claude"}})
        if request.method == "POST" and request.url.path.endswith("/requests/req-1/response"):
            seen.append(b"response")
            return httpx.Response(200, json={})
        return httpx.Response(404)

    async def run():
        worker = Worker("http://testserver", "worker", "token")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await worker.service_workspace_request(client)

    asyncio.run(run())
    assert len(seen) == 1
    assert seen == [b"response"]
