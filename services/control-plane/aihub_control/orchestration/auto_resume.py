"""Wake sessions up once the provider limit that stopped them has been refilled."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from ..models import AccountLimit, AgentEvent, Attachment, Session

RESUME_TEXT = "Лимит восстановился — продолжай с того места, где остановился."
CROSS_ACCOUNT_RESUME_MODE = "native"
# Claude: "You've hit your session limit · resets 12am (Europe/Moscow)"; Codex: "You've hit your usage limit".
# Any window name: "session", "weekly", "Opus", "5-hour"… (the CLI renamed them over time).
LIMIT_RE = re.compile(
    r"you(?:'|’)?ve hit your (?:[\w.-]+ ){0,2}limit|you have hit your (?:[\w.-]+ ){0,2}limit|usage limit reached|rate limit reached",
    re.IGNORECASE,
)
RESETS_RE = re.compile(r"resets\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([^)]+)\))?", re.IGNORECASE)
DEFAULT_TZ = "Europe/Moscow"
# The reset moment is approximate: give the provider a little slack and never retry in a tight loop.
SLACK = timedelta(minutes=2)
MIN_DELAY = timedelta(minutes=10)
FALLBACK_DELAY = timedelta(hours=1)


def is_limit_message(text: str) -> bool:
    return bool(LIMIT_RE.search(text or ""))


def parse_reset(text: str, now: datetime) -> datetime | None:
    match = RESETS_RE.search(text or "")
    if not match:
        return None
    hour, minute, meridiem, zone = int(match[1]), int(match[2] or 0), (match[3] or "").lower(), match[4]
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    try:
        tz = ZoneInfo(zone or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(DEFAULT_TZ)
    local = now.astimezone(tz)
    reset = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= local:
        reset += timedelta(days=1)
    return reset.astimezone(timezone.utc)


def _account_reset(db, account_id: str | None, now: datetime) -> datetime | None:
    if not account_id:
        return None
    rows = db.scalars(select(AccountLimit).where(AccountLimit.account_id == account_id)).all()
    # The exhausted window decides; with none at the edge use the nearest future reset.
    resets = [row.resets_at for row in rows if row.resets_at and row.used_percent >= 90]
    resets = resets or [row.resets_at for row in rows if row.resets_at]
    future = [datetime.fromtimestamp(value, timezone.utc) for value in resets if value > now.timestamp()]
    return max(future) if future else None


def schedule_if_limited(db, session: Session, now: datetime | None = None) -> datetime | None:
    """Called when a session fails: if the last answer was a limit hit, remember when to resume."""
    now = now or datetime.now(timezone.utc)
    recent = db.scalars(
        select(AgentEvent)
        .where(AgentEvent.session_id == session.id, AgentEvent.kind == "message")
        .order_by(AgentEvent.cursor.desc())
        .limit(3)
    ).all()
    text = next(
        (str(event.payload.get("text", "")) for event in recent if is_limit_message(str(event.payload.get("text", "")))),
        None,
    )
    if text is None or not session.engine_session_ref:
        return None
    resume_at = parse_reset(text, now) or _account_reset(db, session.account_profile_id, now) or now + FALLBACK_DELAY
    session.resume_at = max(resume_at + SLACK, now + MIN_DELAY)
    db.add(AgentEvent(
        session_id=session.id, kind="session.resume_scheduled", source="native",
        payload={"resume_at": session.resume_at.isoformat(), "reason": "лимит провайдера"},
    ))
    return session.resume_at


def resume_session(db, original: Session, text: str, attachment_ids=None, model=None, fresh=False, effort=None,
                   permission_mode=None, user=None, account_profile_id=None, trigger=None) -> Session:
    """Continue a finished session in place: the same session runs again on the same agent conversation (the
    owner opens a new session when they want one). Personal chats keep a child per message (chat_id threads)."""
    from ..analytics.runs import create_run
    trigger = trigger or ("retry_after_failure" if original.status == "failed" and original.resume_at is None else "continue")
    original.resume_at = None
    if not original.chat_id:
        if model:
            original.model = model
        original.context_fresh = fresh
        if account_profile_id:
            original.account_profile_id = account_profile_id
        if effort:
            original.mcp_config = {**(original.mcp_config or {}), "effort": effort}
        if permission_mode:
            original.permission_mode = permission_mode
        if original.permission_mode == "ask" and original.engine == "claude_code" and not (original.mcp_config or {}).get("user_id"):
            owner_id = user.id if user else None
            if owner_id:
                from ..routers.chats import _mcp_config
                original.mcp_config = {**(original.mcp_config or {}), "mcpServers": _mcp_config()["mcpServers"], "user_id": owner_id}
        original.status = "queued"
        original.status_source = "native"
        run = create_run(db, original, trigger)
        db.add(AgentEvent(session_id=original.id, run_id=run.id, kind="session.status", source="native", payload={"status": "queued", "reason": "продолжение"}))
        db.add(AgentEvent(
            session_id=original.id, kind="message", source="native",
            payload={"role": "user", "text": text, "attachment_ids": attachment_ids or []},
        ))
        return original
    child = Session(
        task_id=original.task_id,
        project_id=original.project_id,
        worker_id=original.worker_id,
        engine=original.engine,
        provider=original.provider,
        model=model or original.model,
        auth_mode=original.auth_mode,
        workdir=original.workdir,
        branch=original.branch,
        parent_session_id=original.id,
        account_profile_id=account_profile_id or original.account_profile_id,
        workspace_ref=original.workspace_ref,
        title=original.title,
        engine_session_ref=original.engine_session_ref,
        context_tokens=original.context_tokens,
        context_fresh=fresh,
        chat_id=original.chat_id,
        pinned=original.pinned,
        archived=original.archived,
        mcp_config={**(original.mcp_config or {}), **({"effort": effort} if effort else {})} if original.mcp_config or effort else None,
        permission_mode=permission_mode or original.permission_mode,
    )
    if child.permission_mode == "ask" and child.engine == "claude_code" and not (child.mcp_config or {}).get("user_id"):
        # "Ask" needs the hub MCP permission tool and a user to issue its scoped token for.
        owner_id = user.id if user else (original.mcp_config or {}).get("user_id")
        if owner_id:
            from ..routers.chats import _mcp_config
            child.mcp_config = {**(child.mcp_config or {}), "mcpServers": _mcp_config()["mcpServers"], "user_id": owner_id}
    db.add(child)
    db.flush()
    create_run(db, child, trigger)
    # The composer uploads files to the session on screen (the finished one); the continuation is a new
    # session and the worker fetches only that session's attachments: move them over.
    for attachment_id in (attachment_ids or [])[:10]:
        attachment = db.get(Attachment, str(attachment_id))
        if attachment and attachment.session_id == original.id:
            attachment.session_id = child.id
    db.add(AgentEvent(
        session_id=child.id, kind="message", source="native",
        payload={"role": "user", "text": text, "attachment_ids": attachment_ids or []},
    ))
    return child


def resume_due(db, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    due = db.scalars(
        select(Session).where(Session.resume_at.is_not(None), Session.resume_at <= now)
    ).all()
    for session in due:
        if session.status in {"completed", "failed", "offline"}:
            # Automatic resume is deliberately account-sticky.  Changing an account is
            # only allowed through the explicit continue-on-account user action.
            resume_session(db, session, RESUME_TEXT, account_profile_id=None, trigger="auto_resume")
        else:
            session.resume_at = None  # someone already woke it up
    db.commit()
    return len(due)
