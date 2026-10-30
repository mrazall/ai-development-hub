"""Settings changed in the panel override the env default until reset."""
import pytest

from test_api_integration import admin_token, auth, clean_schema, client

pytestmark = pytest.mark.integration


def _by_key(items):
    return {item["key"]: item for item in items}


def test_panel_setting_overrides_env_and_resets(client, admin_token, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AIHUB_WORKER_SHELL_HINT", "from-env")
    listed = _by_key(client.get("/api/v0/system/settings", headers=auth(admin_token)).json())
    assert listed["worker_shell_hint"] == {**listed["worker_shell_hint"], "value": "from-env", "source": "env"}

    changed = client.put("/api/v0/system/settings/worker_shell_hint", headers=auth(admin_token),
                         json={"value": "ssh my-box"})
    assert _by_key(changed.json())["worker_shell_hint"]["value"] == "ssh my-box"
    assert _by_key(changed.json())["worker_shell_hint"]["source"] == "panel"

    # The value is used: login instructions for an account show the panel's command.
    client.post("/api/v0/workers", headers=auth(admin_token), json={"id": "w1", "host": "local", "kind": "linux"})
    client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-a", "name": "Claude", "kind": "claude_code_subscription", "worker_id": "w1",
    })
    steps = client.post("/api/v0/accounts/claude-a/login-instructions", headers=auth(admin_token)).json()["steps"]
    assert steps[0]["command"] == "ssh my-box"

    reset = client.delete("/api/v0/system/settings/worker_shell_hint", headers=auth(admin_token)).json()
    assert _by_key(reset)["worker_shell_hint"]["value"] == "from-env"


def test_invalid_values_are_rejected(client, admin_token):  # noqa: F811
    bad = [("public_url", "not a url"), ("chat_engine", "gpt"), ("health_interval_s", -5), ("no_such", "x")]
    for key, value in bad:
        response = client.put(f"/api/v0/system/settings/{key}", headers=auth(admin_token), json={"value": value})
        assert response.status_code in {404, 422}, (key, response.text)


def test_obsidian_vault_reaches_the_panel(client, admin_token):  # noqa: F811
    # Empty by default: the panel hides "Open in Obsidian" instead of linking to someone else's vault name.
    assert client.get("/api/v0/system/info", headers=auth(admin_token)).json()["obsidian_vault"] == ""
    client.put("/api/v0/system/settings/obsidian_vault", headers=auth(admin_token), json={"value": "Notes"})
    assert client.get("/api/v0/system/info", headers=auth(admin_token)).json()["obsidian_vault"] == "Notes"


def test_login_instructions_use_the_shell_the_worker_reports(client, admin_token, monkeypatch):  # noqa: F811
    monkeypatch.delenv("AIHUB_WORKER_SHELL_HINT", raising=False)
    worker = client.post("/api/v0/workers", headers=auth(admin_token),
                         json={"id": "box", "host": "box", "kind": "linux"}).json()
    client.post("/api/v0/workers/box/capabilities", headers=auth(worker["worker_token"]),
                json={"engines": {}, "shell_hint": "ssh -t dev@box"})
    client.post("/api/v0/accounts", headers=auth(admin_token), json={
        "id": "claude-b", "name": "Claude", "kind": "claude_code_subscription", "worker_id": "box",
    })
    steps = lambda: client.post("/api/v0/accounts/claude-b/login-instructions", headers=auth(admin_token)).json()["steps"]
    assert steps()[0]["command"] == "ssh -t dev@box"
    # The owner's per-worker line wins over what the worker reports.
    client.put("/api/v0/system/settings/worker_shell_hint", headers=auth(admin_token),
               json={"value": "box=ssh -t my-alias"})
    assert steps()[0]["command"] == "ssh -t my-alias"
