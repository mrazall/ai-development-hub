"""Errors from the panel in a browser: a page that crashed is written to the hub log (docker logs control-plane).

Only what helps to find the cause — message, stack, page path, screen size, browser — capped in size; no request
bodies or tokens. Rate-limited per user so a crash loop cannot flood the log.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import current_user
from ..redaction import redact_string

router = APIRouter(tags=["client-errors"])
log = logging.getLogger("aihub.client")
_recent: dict[str, deque[float]] = defaultdict(deque)
LIMIT_PER_MINUTE = 10


class ClientErrorIn(BaseModel):
    message: str = Field(max_length=500)
    stack: str = Field(default="", max_length=4000)
    where: str = Field(default="", max_length=40)
    path: str = Field(default="", max_length=300)
    viewport: str = Field(default="", max_length=20)
    user_agent: str = Field(default="", max_length=300)


@router.post("/client-errors", status_code=204)
def client_error(data: ClientErrorIn, user=Depends(current_user)) -> None:
    now = time.monotonic()
    recent = _recent[str(user.id)]
    while recent and now - recent[0] > 60:
        recent.popleft()
    if len(recent) >= LIMIT_PER_MINUTE:
        return
    recent.append(now)
    log.warning("client error [%s] for %s at %s (%s, %s): %s\n%s", data.where, user.username, data.path,
                data.viewport, data.user_agent, redact_string(data.message)[0], redact_string(data.stack)[0])

