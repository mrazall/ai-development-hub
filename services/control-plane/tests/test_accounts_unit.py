from pathlib import Path

from aihub_control.accounts.service import account_config_dir, secret_fingerprint, write_secret
from aihub_control.schemas import AccountIn


def test_secret_fingerprint_is_display_safe():
    value = "sk-test-secret-value"
    fingerprint = secret_fingerprint(value)
    assert fingerprint == "".join((__import__("hashlib").sha256(value.encode()).hexdigest()[:8], value[-4:]))
    assert value not in fingerprint


def test_secret_is_written_with_restricted_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("AIHUB_ACCOUNTS_SECRET_DIR", str(tmp_path))
    path = Path(write_secret("demo", "secret-value"))
    assert path.read_text() == "secret-value"
    assert path.stat().st_mode & 0o777 == 0o600


def test_subscription_config_dirs_are_isolated():
    assert account_config_dir("claude_code_subscription", "one") == "~/.aihub/accounts/one/claude"
    assert account_config_dir("claude_code_subscription", "two") != account_config_dir("claude_code_subscription", "one")
    assert account_config_dir("openai_api", "one") is None


def test_account_id_validation_is_contract_compatible():
    assert AccountIn(id="claude-one", name="Claude", kind="claude_code_subscription", worker_id="w").id == "claude-one"


def test_subscription_check_requires_official_credentials_without_reading_them(tmp_path, monkeypatch):
    from aihub_agents import accounts

    config_dir = tmp_path / "claude"
    config_dir.mkdir()
    called = []
    monkeypatch.setattr(accounts.subprocess, "run", lambda *args, **kwargs: called.append(args) or None)

    status, detail = accounts.check_subscription("claude_code_subscription", str(config_dir))

    assert (status, detail) == ("pending_login", "official login credentials are not present")
    assert called == []


def test_subscription_check_runs_official_cli_after_credential_presence(tmp_path, monkeypatch):
    from aihub_agents import accounts

    config_dir = tmp_path / "codex"
    config_dir.mkdir()
    # The content is intentionally not a credential; implementation only
    # checks the documented file name and never reads it.
    (config_dir / "auth.json").write_text("do-not-read", encoding="utf-8")
    calls = []

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(accounts.subprocess, "run", fake_run)
    assert accounts.check_subscription("codex_subscription", str(config_dir)) == (
        "connected",
        "official CLI check succeeded",
    )
    assert calls[0][0] == ["codex", "login", "status"]
