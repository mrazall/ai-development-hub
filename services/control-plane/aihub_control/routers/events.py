import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..auth import current_user, db_dep, user_from_token
from ..db import get_session_factory
from ..deps import is_admin, visible_events
from ..schemas import EventOut
from sqlalchemy import select
from ..tickets import consume

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/stream-ticket")
def stream_ticket(user=Depends(current_user)):
    from ..tickets import issue
    from ..schemas import StreamTicket

    ticket, ttl = issue(user.id)
    return StreamTicket(ticket=ticket, expires_in=ttl)


@router.get("", response_model=list[EventOut])
def events(
    after: int = 0,
    session_id: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    newest: bool = False,
    chat: bool = False,
    view: str | None = Query(None, pattern="^(chat|activity|events)$"),
    user=Depends(current_user),
    db=Depends(db_dep),
):
    # newest=true: the latest `limit` events (a long session's history ends where the live stream starts).
    # view=chat|activity|events: drop engine bookkeeping per tab (see visible_events); chat=true is view=chat.
    return visible_events(db, user, after, session_id, limit, newest=newest, view=view or ("chat" if chat else None))


@router.get("/stream")
async def event_stream(after: int = Query(0), session_id: str | None = Query(None), ticket: str | None = Query(None), request: Request = None, db=Depends(db_dep)):
    ticket = ticket or request.scope.get("aihub_stream_ticket")
    if ticket:
        from ..models import User
        from ..tickets import consume
        # The middleware preserves the original ticket in this private scope value.
        raw_ticket = request.scope.get("aihub_stream_ticket", ticket)
        owner = request.scope.get("aihub_stream_user")
        if not owner or not consume(raw_ticket, owner):
            raise HTTPException(401, "invalid or expired stream ticket")
        user = db.get(User, owner)
        if not user:
            raise HTTPException(401, "invalid stream ticket owner")
    else:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "authentication required")
        user = user_from_token(auth[7:], db)
    if request and request.headers.get("last-event-id"):
        after = int(request.headers["last-event-id"])

    if after < 0:
        # after=-1: only what happens from now on (the caller loads history separately); replaying
        # everything from cursor 0 sent every event of every session on each page load.
        from ..models import AgentEvent
        from sqlalchemy import func

        after = db.scalar(select(func.max(AgentEvent.cursor))) or 0

    async def generate():
        cursor = after
        last_keepalive = asyncio.get_running_loop().time()
        while True:
            if await request.is_disconnected():
                break
            # Read and serialize, then release the session BEFORE yielding: a slow or stalled client
            # must not keep a transaction (and its table locks) open while the generator is suspended.
            _, factory = get_session_factory()
            db = factory()
            try:
                batch = [
                    (event.cursor, event.kind, EventOut.model_validate(event).model_dump_json())
                    for event in visible_events(db, user, cursor, session_id=session_id)
                ]
            finally:
                db.close()
            for event_cursor, kind, data in batch:
                cursor = event_cursor
                yield f"id: {event_cursor}\nevent: {kind}\ndata: {data}\n\n"
            now = asyncio.get_running_loop().time()
            if now - last_keepalive >= 15:
                last_keepalive = now
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
