"""Token usage statistics: Claude runs carry their own API price, Codex turns are priced from the settings."""
import pytest

from test_api_integration import admin_token, auth, clean_schema, client, make_project

pytestmark = pytest.mark.integration


def _session(client, token, engine, model):  # noqa: F811
    response = client.post("/api/v0/sessions", headers=auth(token), json={
        "project_id": "demo", "worker_id": "worker-a", "engine": engine, "provider": "x", "model": model,
        "auth_mode": "subscription", "workdir": "/tmp/project",
    })
    assert response.status_code == 200
    return response.json()["id"]


def test_usage_by_model_with_api_prices(client, admin_token):  # noqa: F811
    make_project(client, admin_token)
    claude = _session(client, admin_token, "claude_code", "claude-opus-5-5")
    codex = _session(client, admin_token, "codex", "gpt-5.6-luna")
    client.post(f"/api/v0/sessions/{claude}/events", headers=auth(admin_token), json=[
        {"kind": "message", "payload": {"raw_type": "result", "cost_usd": 1.5, "usage": {
            "input_tokens": 100, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50,
            "output_tokens": 200}}},
        {"kind": "output", "payload": {"text": "not usage"}},
    ])
    turn = {"kind": "message", "payload": {"raw_type": "turn.completed", "usage": {
        "input_tokens": 1_000_000, "cached_input_tokens": 600_000, "output_tokens": 100_000}}}
    client.post(f"/api/v0/sessions/{codex}/events", headers=auth(admin_token), json=[turn, turn])

    stats = client.get("/api/v0/stats/usage?days=0", headers=auth(admin_token)).json()
    by_model = {row["model"]: row for row in stats["by_model"]}
    opus = by_model["claude-opus-5-5"]
    assert {key: opus[key] for key in ("input", "cache_read", "cache_write", "output", "cost_usd", "sessions")} == {
        "input": 100, "cache_read": 1000, "cache_write": 50, "output": 200, "cost_usd": 1.5, "sessions": 1}
    # Codex counts cached input inside input_tokens: 400k fresh + 600k cached per turn, two turns.
    luna = by_model["gpt-5.6-luna"]
    assert (luna["input"], luna["cache_read"], luna["output"], luna["runs"]) == (800_000, 1_200_000, 200_000, 2)
    assert luna["cost_usd"] == 0 and luna["unpriced_tokens"] == 2_200_000

    client.put("/api/v0/system/settings/model_prices", headers=auth(admin_token),
               json={"value": "gpt-5.6-luna=1,0.1,10"})
    stats = client.get("/api/v0/stats/usage?days=30", headers=auth(admin_token)).json()
    luna = {row["model"]: row for row in stats["by_model"]}["gpt-5.6-luna"]
    # 0.8M fresh × $1 + 1.2M cached × $0.1 + 0.2M output × $10 = 0.8 + 0.12 + 2.0
    assert luna["cost_usd"] == pytest.approx(2.92) and luna["unpriced_tokens"] == 0
    assert stats["total"]["cost_usd"] == pytest.approx(4.42) and stats["total"]["sessions"] == 2
    assert sum(day["tokens"] for day in stats["by_day"]) == stats["total"]["tokens"]


def test_usage_is_for_admins(client, admin_token):  # noqa: F811
    from aihub_control.auth import hash_password
    from aihub_control.db import get_session_factory
    from aihub_control.models import User

    _, factory = get_session_factory()
    db = factory()
    db.add(User(username="viewer", password_hash=hash_password("viewer-password"), role="viewer"))
    db.commit()
    db.close()
    token = client.post("/api/v0/auth/login", json={"username": "viewer", "password": "viewer-password"}).json()
    assert client.get("/api/v0/stats/usage", headers=auth(token["access_token"])).status_code == 403
