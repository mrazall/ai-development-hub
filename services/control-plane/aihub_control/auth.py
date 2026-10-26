import hashlib
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .db import get_session_factory
from .models import User, WorkerToken
from .schemas import Token

ph = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def hash_password(password):
    return ph.hash(password)


def verify_password(stored, password):
    try:
        return ph.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def issue_token(user: User, settings: Settings):
    exp = datetime.now(timezone.utc) + timedelta(seconds=settings.access_token_ttl_s)
    return Token(
        access_token=jwt.encode(
            {"sub": user.id, "role": user.role, "exp": exp}, settings.secret_key, algorithm="HS256"
        ),
        expires_in=settings.access_token_ttl_s,
    )


# --- Scoped knowledge tokens ---
def issue_scoped_token(user: User, scopes: set[str] | list[str] | tuple[str, ...], ttl: int = 3600,
                       settings: Settings | None = None):
    """Issue a short-lived token accepted only by explicitly scoped endpoints."""
    settings = settings or Settings()
    ttl = max(1, min(int(ttl), 3600))
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return Token(
        access_token=jwt.encode(
            {"sub": user.id, "role": user.role, "scope": " ".join(sorted(set(scopes))), "exp": exp},
            settings.secret_key, algorithm="HS256",
        ),
        expires_in=ttl,
    )


def db_dep():
    _, session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(db_dep)):
    if not credentials:
        raise HTTPException(401, "authentication required")
    try:
        settings = Settings()
        data = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
        if data.get("scope"):
            raise HTTPException(403, "scoped token is limited to its scope")
        user = db.get(User, data["sub"])
    except (jwt.DecodeError, jwt.ExpiredSignatureError, KeyError):
        user = None
    if not user:
        raise HTTPException(401, "invalid token")
    return user


def require_scope(scope: str) -> Callable:
    """Accept a normal user token or a scoped token carrying ``scope``."""
    def dependency(credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(db_dep)):
        if not credentials:
            raise HTTPException(401, "authentication required")
        try:
            data = jwt.decode(credentials.credentials, Settings().secret_key, algorithms=["HS256"])
        except (jwt.DecodeError, jwt.ExpiredSignatureError, KeyError):
            raise HTTPException(401, "invalid token")
        scopes = set(str(data.get("scope", "")).split())
        if data.get("scope") and scope not in scopes:
            raise HTTPException(403, "required scope missing")
        user = db.get(User, data.get("sub"))
        if not user:
            raise HTTPException(401, "invalid token")
        return user
    return dependency


# Argon2 is deliberately slow (~0.5 s CPU here) and workers authenticate every event post, so a
# token that verified once is remembered by its SHA-256; revocation is still checked on each use.
_verified_worker_tokens: dict[str, str] = {}


def _worker_token(db, raw: str):
    digest = hashlib.sha256(raw.encode()).hexdigest()
    cached = _verified_worker_tokens.get(digest)
    if cached:
        record = db.get(WorkerToken, cached)
        if record and record.revoked_at is None:
            return record
        _verified_worker_tokens.pop(digest, None)
    for record in db.query(WorkerToken).filter(WorkerToken.revoked_at.is_(None)).all():
        try:
            if ph.verify(record.token_hash, raw):
                _verified_worker_tokens[digest] = record.id
                return record
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            continue
    return None


def worker_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(db_dep)
):
    if not credentials:
        raise HTTPException(401, "authentication required")
    record = _worker_token(db, credentials.credentials)
    if record:
        return record
    raise HTTPException(401, "invalid worker token")


def current_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(db_dep)
):
    if not credentials:
        raise HTTPException(401, "authentication required")
    try:
        settings = Settings()
        data = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
        if data.get("scope"):
            raise HTTPException(403, "scoped token is limited to its scope")
        user = db.get(User, data["sub"])
        if user:
            return user
    except (jwt.DecodeError, jwt.ExpiredSignatureError, KeyError):
        pass
    record = _worker_token(db, credentials.credentials)
    if record:
        return record
    raise HTTPException(401, "invalid token")


def admin_only(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "admin role required")
    return user


def write_user(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "admin role required for write operation")
    return user


def user_from_token(token: str, db):
    """Validate a browser access token without relying on an Authorization header."""
    try:
        data = jwt.decode(token, Settings().secret_key, algorithms=["HS256"])
        user = db.get(User, data["sub"])
    except (jwt.DecodeError, jwt.ExpiredSignatureError, KeyError, TypeError):
        user = None
    if not user:
        raise HTTPException(401, "invalid token")
    return user
