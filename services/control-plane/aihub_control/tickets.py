"""Short-lived, single-use SSE tickets kept only in this process."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from threading import Lock

_tickets: dict[str, tuple[str, datetime]] = {}
_lock = Lock()


def issue(user_id: str, ttl: int = 60) -> tuple[str, int]:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    with _lock:
        for key in [key for key, (_, expires) in _tickets.items() if expires <= now]:
            del _tickets[key]  # expired tickets must not accumulate in memory
        _tickets[digest] = (user_id, now + timedelta(seconds=ttl))
    return raw, ttl


def consume(raw: str, user_id: str) -> bool:
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with _lock:
        item = _tickets.get(digest)
        if not item:
            return False
        owner, expires = item
        if not secrets.compare_digest(owner, user_id) or expires <= datetime.now(timezone.utc):
            return False
        _tickets.pop(digest, None)
        return True


def owner_for(raw: str) -> str | None:
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with _lock:
        item = _tickets.get(digest)
    if not item or item[1] <= datetime.now(timezone.utc):
        return None
    return item[0]
