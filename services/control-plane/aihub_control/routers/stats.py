"""Token usage of agent sessions and chats, and what it would have cost on the API.

Engines report usage per run: Claude Code a `result` (with the API-equivalent `cost_usd` it computes itself),
Codex a `turn.completed` per turn (no price). Tokens are normalized to fresh input / cache read / cache write /
output; a run without `cost_usd` is priced from the `model_prices` setting, or counted as unpriced.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from ..auth import current_user, db_dep
from ..deps import is_admin
from ..models import AccountProfile, AgentEvent, Session
from ..system_settings import get_setting

router = APIRouter(prefix="/stats", tags=["stats"])

from ..analytics.usage import USAGE_EVENTS, TOKEN_KINDS, normalize, parse_prices, price_of


def _bucket() -> dict:
    return {**{kind: 0 for kind in TOKEN_KINDS}, "tokens": 0, "cost_usd": 0.0, "unpriced_tokens": 0,
            "runs": 0, "sessions": set()}


def _add(bucket: dict, session_id: str, tokens: dict[str, int], cost: float | None) -> None:
    for kind in TOKEN_KINDS:
        bucket[kind] += tokens[kind]
    total = sum(tokens.values())
    bucket["tokens"] += total
    bucket["runs"] += 1
    bucket["sessions"].add(session_id)
    if cost is None:
        bucket["unpriced_tokens"] += total
    else:
        bucket["cost_usd"] += cost


def _out(bucket: dict) -> dict:
    return {**{k: v for k, v in bucket.items() if k != "sessions"}, "sessions": len(bucket["sessions"]),
            "cost_usd": round(bucket["cost_usd"], 4)}


@router.get("/usage")
def usage(days: int = Query(default=30, ge=0, le=3650), user=Depends(current_user), db=Depends(db_dep)):
    """Totals and breakdowns by model, account, project and day; days=0 means all time."""
    if not is_admin(user):
        raise HTTPException(403, "admin only")
    prices = parse_prices(get_setting(db, "model_prices"))
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    query = (
        select(AgentEvent.ts, AgentEvent.payload, Session.id, Session.engine, Session.model,
               Session.account_profile_id, Session.project_id)
        .join(Session, Session.id == AgentEvent.session_id)
        .where(AgentEvent.kind.in_(["message", "output"]),
               AgentEvent.payload["raw_type"].as_string().in_(USAGE_EVENTS))
    )
    if since:
        query = query.where(AgentEvent.ts >= since)
    total = _bucket()
    by_model: dict[tuple[str, str], dict] = defaultdict(_bucket)
    by_account: dict[str, dict] = defaultdict(_bucket)
    by_project: dict[str, dict] = defaultdict(_bucket)
    by_day: dict[tuple[date, str], dict] = defaultdict(_bucket)
    for ts, payload, session_id, engine, model, account_id, project_id in db.execute(query):
        payload = payload or {}
        usage_payload = payload.get("usage")
        if not isinstance(usage_payload, dict):
            continue
        tokens = normalize(engine or "", usage_payload)
        if not any(tokens.values()):
            continue
        model = model or "unknown"
        cost = payload.get("cost_usd")
        if not isinstance(cost, (int, float)):
            cost = price_of(tokens, prices[model]) if model in prices else None
        for bucket in (total, by_model[(engine or "", model)], by_account[account_id or ""],
                       by_project[project_id or ""], by_day[((ts or datetime.now(timezone.utc)).date(), model)]):
            _add(bucket, session_id, tokens, cost)
    names = {a.id: a.name for a in db.scalars(select(AccountProfile))}
    return {
        "days": days,
        "since": since,
        "priced_models": sorted(prices),
        "total": _out(total),
        "by_model": sorted(({"engine": engine, "model": model, **_out(b)} for (engine, model), b in by_model.items()),
                           key=lambda row: -row["tokens"]),
        "by_account": sorted(({"account_id": key or None, "name": names.get(key, key or "—"), **_out(b)}
                              for key, b in by_account.items()), key=lambda row: -row["tokens"]),
        "by_project": sorted(({"project_id": key or None, **_out(b)} for key, b in by_project.items()),
                             key=lambda row: -row["tokens"]),
        "by_day": sorted(({"date": day.isoformat(), "model": model, **_out(b)} for (day, model), b in by_day.items()),
                         key=lambda row: (row["date"], row["model"])),
    }

# --- efficiency
from ..analytics import efficiency as efficiency_analytics


# The tab asks for the summary and the task list at once, and the computation is CPU-bound Python (it holds the
# GIL, so it slows every other request of the hub). Results are reused while nothing they depend on changed:
# the newest event, session and task, the prices, and the minute (the "last N days" window moves).
_EFFICIENCY_CACHE: dict = {}


def _efficiency_fingerprint(db):
    from sqlalchemy import func, select as _select

    from ..models import AgentEvent, ExecutionRun, Session, Task
    from ..system_settings import get_setting

    return (
        db.scalar(_select(func.max(AgentEvent.cursor))),
        db.scalar(_select(func.max(Session.updated_at))), db.scalar(_select(func.count(Session.id))),
        db.scalar(_select(func.max(Task.updated_at))), db.scalar(_select(func.count(ExecutionRun.id))),
        get_setting(db, 'model_prices'), datetime.now(timezone.utc).strftime('%Y%m%d%H%M'),
    )


def _efficiency_data(db, days, project_id, model, account_id, role, status):
    key = (days, project_id, model, account_id, role, status)
    fingerprint = _efficiency_fingerprint(db)
    cached = _EFFICIENCY_CACHE.get(key)
    if cached and cached[0] == fingerprint:
        return cached[1]
    data = efficiency_analytics.collect(db, days, project_id, model, account_id, role, status)
    if len(_EFFICIENCY_CACHE) > 64:
        _EFFICIENCY_CACHE.clear()
    _EFFICIENCY_CACHE[key] = (fingerprint, data)
    return data


@router.get('/efficiency')
def efficiency(days: int = Query(30, ge=0, le=3650), project_id: str | None = None,
               model: str | None = None, account_id: str | None = None,
               role: str | None = Query(None, pattern='^(orchestrator|executor|single)$'), status: str | None = None,
               user=Depends(current_user), db=Depends(db_dep)):
    if not is_admin(user):
        raise HTTPException(403, 'admin only')
    return _efficiency_data(db, days, project_id, model, account_id, role, status)[0]


@router.get('/tasks')
def efficiency_tasks(days: int = Query(30, ge=0, le=3650), project_id: str | None = None,
                     model: str | None = None, account_id: str | None = None,
                     role: str | None = Query(None, pattern='^(orchestrator|executor|single)$'), status: str | None = None,
                     sort: str = Query('cost', pattern='^(cost|tokens|wall|updated|retries)$'),
                     order: str = Query('desc', pattern='^(asc|desc)$'), limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0), q: str = '', user=Depends(current_user), db=Depends(db_dep)):
    if not is_admin(user):
        raise HTTPException(403, 'admin only')
    _, items, rows, *_ = _efficiency_data(db, days, project_id, model, account_id, role, status)
    items = list(items)  # the cached list stays as computed
    if q:
        items = [item for item in items if q.casefold() in item['title'].casefold() or q.casefold() in item['task_id'].casefold()]
    key = {'cost': 'cost_usd', 'tokens': 'tokens', 'wall': 'wall_s', 'retries': 'retries'}.get(sort)
    def value(item):
        return rows[item['task_id']]['updated'] if sort == 'updated' else item[key]
    items.sort(key=lambda x: x['task_id'])
    present = [x for x in items if value(x) is not None]
    missing = [x for x in items if value(x) is None]
    present.sort(key=value, reverse=order == 'desc')
    items = present + missing
    return {'total': len(items), 'items': items[offset:offset + limit]}


@router.get('/tasks/{task_id}')
def efficiency_task(task_id: str, days: int = Query(30, ge=0, le=3650), project_id: str | None = None,
                    model: str | None = None, account_id: str | None = None,
                    role: str | None = Query(None, pattern='^(orchestrator|executor|single)$'), status: str | None = None,
                    user=Depends(current_user), db=Depends(db_dep)):
    if not is_admin(user):
        raise HTTPException(403, 'admin only')
    result = efficiency_analytics.detail(_efficiency_data(db, days, project_id, model, account_id, role, status), task_id)
    if result is None:
        raise HTTPException(404, 'task not found')
    return result
