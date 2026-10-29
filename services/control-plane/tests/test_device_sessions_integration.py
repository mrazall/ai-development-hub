from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aihub_control.auth import hash_password
from aihub_control.db import get_session_factory
from aihub_control.models import DeviceSession, User
from aihub_control.routers.auth import REFRESH_COOKIE
from test_api_integration import app
from test_api_integration import clean_schema as clean_schema_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def owner():
    _, factory = get_session_factory()
    with factory() as db:
        db.add(User(username="owner", password_hash=hash_password("owner-password"), role="admin"))
        db.commit()


def _login(client: TestClient):
    response = client.post("/api/v0/auth/login", json={"username": "owner", "password": "owner-password"})
    assert response.status_code == 200
    return response


def _devices():
    _, factory = get_session_factory()
    with factory() as db:
        return list(db.scalars(select(DeviceSession)))


def _idle(days: int):
    """Pretend the device was last used `days` ago."""
    _, factory = get_session_factory()
    with factory() as db:
        for device in db.scalars(select(DeviceSession)):
            device.expires_at = datetime.now(timezone.utc) + timedelta(days=30 - days)
        db.commit()


def test_login_keeps_the_device_signed_in_and_refresh_rotates(owner):
    with TestClient(app) as client:
        login = _login(client)
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=2592000" in cookie
        first = client.cookies.get(REFRESH_COOKIE)
        assert first and first != _devices()[0].token_hash  # only the hash is stored

        refreshed = client.post("/api/v0/auth/refresh")
        assert refreshed.status_code == 200
        token = refreshed.json()["access_token"]
        me = client.get("/api/v0/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["username"] == "owner"
        assert client.cookies.get(REFRESH_COOKIE) != first

    # Another tab still holding the previous token right after the rotation is not signed out.
    with TestClient(app) as other_tab:
        other_tab.cookies.set(REFRESH_COOKIE, first, path="/api/v0/auth")
        assert other_tab.post("/api/v0/auth/refresh").status_code == 200


def test_activity_moves_the_30_days_and_idleness_ends_the_session(owner):
    with TestClient(app) as client:
        _login(client)
        _idle(29)
        assert client.post("/api/v0/auth/refresh").status_code == 200
        assert _devices()[0].expires_at > datetime.now(timezone.utc) + timedelta(days=29)
        _idle(31)
        assert client.post("/api/v0/auth/refresh").status_code == 401


def test_logout_ends_only_this_device(owner):
    with TestClient(app) as phone, TestClient(app) as laptop:
        _login(phone)
        _login(laptop)
        assert phone.post("/api/v0/auth/logout").status_code == 204
        assert phone.post("/api/v0/auth/refresh").status_code == 401
        assert laptop.post("/api/v0/auth/refresh").status_code == 200


def test_refresh_without_or_with_a_forged_cookie(owner):
    with TestClient(app) as client:
        assert client.post("/api/v0/auth/refresh").status_code == 401
        client.cookies.set(REFRESH_COOKIE, "forged", path="/api/v0/auth")
        assert client.post("/api/v0/auth/refresh").status_code == 401
