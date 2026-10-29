import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select

from ..auth import current_user, db_dep, issue_token, verify_password
from ..config import Settings
from ..models import DeviceSession, User
from ..schemas import Login, Token

router = APIRouter(prefix="/auth", tags=["auth"])

# A device stays signed in until the owner logs out or it goes unused this long; every refresh moves the limit.
REFRESH_COOKIE = "aihub_refresh"
REFRESH_IDLE = timedelta(days=30)
ROTATION_GRACE = timedelta(seconds=60)
COOKIE_PATH = "/api/v0/auth"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _set_cookie(response: Response, request: Request, raw: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        REFRESH_COOKIE, raw, max_age=int(REFRESH_IDLE.total_seconds()), path=COOKIE_PATH,
        httponly=True, secure=secure, samesite="strict",
    )


def _signed_out() -> JSONResponse:
    response = JSONResponse({"detail": "not signed in"}, status_code=401)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.post("/login", response_model=Token)
def login(data: Login, request: Request, response: Response, db=Depends(db_dep)):
    user = db.scalar(select(User).where(User.username == data.username))
    if not user or not verify_password(user.password_hash, data.password):
        raise HTTPException(401, "invalid credentials")
    raw = secrets.token_urlsafe(32)
    db.add(DeviceSession(
        user_id=user.id, token_hash=_hash(raw), expires_at=datetime.now(timezone.utc) + REFRESH_IDLE,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    ))
    db.commit()
    _set_cookie(response, request, raw)
    return issue_token(user, Settings())


@router.post("/refresh", response_model=Token)
def refresh(request: Request, response: Response, db=Depends(db_dep)):
    """A new access token for a signed-in device; the refresh token is rotated and its 30 days start again."""
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        return _signed_out()
    hashed, now = _hash(raw), datetime.now(timezone.utc)
    device = db.scalar(select(DeviceSession).where(
        or_(DeviceSession.token_hash == hashed, DeviceSession.previous_hash == hashed)
    ))
    user = db.get(User, device.user_id) if device else None
    current = bool(device) and device.token_hash == hashed
    recent_rotation = bool(device and device.rotated_at and now - device.rotated_at <= ROTATION_GRACE)
    if not device or not user or device.revoked_at or device.expires_at <= now or not (current or recent_rotation):
        return _signed_out()
    if current:
        new_raw = secrets.token_urlsafe(32)
        device.previous_hash, device.token_hash, device.rotated_at = hashed, _hash(new_raw), now
        _set_cookie(response, request, new_raw)
    # A tab that sent the just-rotated token gets the new cookie from the other tab's response.
    device.last_used_at, device.expires_at = now, now + REFRESH_IDLE
    db.commit()
    return issue_token(user, Settings())


@router.post("/logout", status_code=204)
def logout(request: Request, db=Depends(db_dep)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        device = db.scalar(select(DeviceSession).where(DeviceSession.token_hash == _hash(raw)))
        if device and not device.revoked_at:
            device.revoked_at = datetime.now(timezone.utc)
            db.commit()
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.get("/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}
