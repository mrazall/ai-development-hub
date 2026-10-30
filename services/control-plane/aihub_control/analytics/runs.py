"""Execution lifecycle snapshots and read-only historical reconstruction."""
from dataclasses import dataclass
from datetime import datetime, timezone

from collections import defaultdict
from typing import Any, NamedTuple

from sqlalchemy import case, select

from ..models import AgentEvent, ExecutionRun, Session


@dataclass
class RunInfo:
    id: str | None
    session_id: str
    run_index: int
    task_id: str | None
    project_id: str
    engine: str | None
    model: str | None
    account_profile_id: str | None
    role: str | None
    orchestration_id: str | None
    trigger: str
    status: str
    failure_reason: str | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    active_s: float | None
    waiting_approval_s: float | None
    waiting_limit_s: float | None
    attribution: str
    first_cursor: int | None
    last_cursor: int | None


def create_run(db, session, trigger):
    db.flush()
    db.scalar(select(Session.id).where(Session.id == session.id).with_for_update())
    previous = db.scalar(select(ExecutionRun).where(ExecutionRun.session_id == session.id).order_by(ExecutionRun.run_index.desc()).limit(1))
    root = session.id if session.role == 'orchestrator' else (session.parent_session_id if session.role == 'executor' else None)
    run = ExecutionRun(session_id=session.id, task_id=session.task_id, project_id=session.project_id,
                       run_index=previous.run_index + 1 if previous else 1, engine=session.engine, model=session.model,
                       account_profile_id=session.account_profile_id, role=session.role, orchestration_id=root,
                       trigger=trigger, queued_at=datetime.now(timezone.utc), status='queued', attribution='exact')
    db.add(run)
    db.flush()
    return run


def latest_run(db, session_id):
    return db.scalar(select(ExecutionRun).where(ExecutionRun.session_id == session_id).order_by(ExecutionRun.run_index.desc()).limit(1))


def update_run(db, run, status, ts, payload):
    if not run:
        return
    if status in ('starting', 'running'):
        run.started_at = run.started_at or ts
        run.status = 'running'
    elif status in ('completed', 'failed', 'cancelled'):
        run.status, run.finished_at = status, ts
        if status == 'failed':
            run.failure_reason = payload.get('reason')
    elif status == 'queued':
        run.status = 'queued'
    events = db.scalars(select(AgentEvent).where(
        AgentEvent.run_id == run.id, AgentEvent.kind == 'session.status'
    ).order_by(AgentEvent.cursor)).all()
    run.waiting_approval_s = _waiting(events, 'approval')
    run.waiting_limit_s = _waiting(events, 'limit')


def _wait_kind(event):
    status = (event.payload or {}).get('status')
    if status == 'waiting_approval':
        return 'approval'
    if status == 'waiting_limit' or (status == 'blocked' and (event.payload or {}).get('reason') == 'limit'):
        return 'limit'
    return None


def _waiting(events, kind):
    total, start, observed = 0.0, None, False
    for event in events:
        if event.kind != 'session.status':
            continue
        current = _wait_kind(event)
        if current == kind and start is None:
            start = event.ts
        elif current != kind and start is not None:
            if event.ts is not None and event.ts >= start:
                total += (event.ts - start).total_seconds()
                observed = True
            start = None
    return total if observed else None


def _active(events):
    total, start, observed = 0.0, None, False
    for event in events:
        if event.kind != 'session.status':
            continue
        status = event.payload.get('status')
        if status == 'running' and start is None:
            start = event.ts
        elif status != 'running' and start is not None:
            total += max(0, (event.ts - start).total_seconds())
            start, observed = None, True
    return total if observed else None


class _Event(NamedTuple):
    """What run reconstruction reads of an event: the payload only for status events (the rest is output)."""
    session_id: str
    cursor: int
    kind: str | None
    ts: datetime | None
    run_id: str | None
    payload: Any


def runs_for_sessions(db, session_ids: list[str]) -> dict[str, list[RunInfo]]:
    result = {sid: [] for sid in session_ids}
    if not session_ids:
        return result
    sessions = db.scalars(select(Session).where(Session.id.in_(session_ids))).all()
    rows = db.scalars(select(ExecutionRun).where(ExecutionRun.session_id.in_(session_ids)).order_by(ExecutionRun.run_index)).all()
    # One pass, grouped by session and by run: filtering the whole event list per session was quadratic
    # (seconds on a real history), and decoding every output payload was most of the rest.
    status_payload = case((AgentEvent.kind == 'session.status', AgentEvent.payload), else_=None)
    events_by_session: dict[str, list[_Event]] = defaultdict(list)
    for row in db.execute(
        select(AgentEvent.session_id, AgentEvent.cursor, AgentEvent.kind, AgentEvent.ts, AgentEvent.run_id, status_payload)
        .where(AgentEvent.session_id.in_(session_ids)).order_by(AgentEvent.cursor)
    ):
        events_by_session[row[0]].append(_Event(row[0], row[1], row[2], row[3], row[4], row[5] or {}))
    runs_by_session: dict[str, list] = defaultdict(list)
    for run in rows:
        runs_by_session[run.session_id].append(run)
    for session in sessions:
        se = events_by_session.get(session.id, [])
        sr = runs_by_session.get(session.id, [])
        if sr:
            by_run: dict[str | None, list[_Event]] = defaultdict(list)
            for e in se:
                by_run[e.run_id].append(e)
            for r in sr:
                ev = by_run.get(r.id, [])
                result[session.id].append(RunInfo(r.id, r.session_id, r.run_index, r.task_id, r.project_id, r.engine, r.model, r.account_profile_id, r.role, r.orchestration_id, r.trigger, r.status, r.failure_reason, r.queued_at, r.started_at, r.finished_at, _active(ev), r.waiting_approval_s, r.waiting_limit_s, r.attribution, ev[0].cursor if ev else None, ev[-1].cursor if ev else None))
            continue
        changed = any(e.kind in ('session.account_switched', 'session.model_changed', 'continue-on-account', 'session.continue_on_account') for e in se)
        groups = []
        for e in se:
            if e.kind == 'session.status' and e.payload.get('status') == 'queued' and groups and any(x.kind == 'session.status' and x.payload.get('status') in ('completed', 'failed', 'cancelled', 'offline') for x in groups[-1]):
                groups.append([])
            if not groups:
                groups.append([])
            groups[-1].append(e)
        for i, group in enumerate(groups):
            statuses = [e for e in group if e.kind == 'session.status']
            if not statuses:
                continue
            def find(values, history=statuses):
                return next((e.ts for e in history if e.payload.get('status') in values), None)
            last = statuses[-1]
            status = last.payload.get('status', 'unknown')
            status = 'running' if status in ('starting', 'running', 'waiting_approval', 'blocked') else status if status in ('queued', 'completed', 'failed', 'cancelled') else 'unknown'
            result[session.id].append(RunInfo(None, session.id, i + 1, session.task_id, session.project_id, session.engine, None if changed else session.model, None if changed else session.account_profile_id, session.role, session.id if session.role == 'orchestrator' else session.parent_session_id if session.role == 'executor' else None, 'unknown', status, last.payload.get('reason') if status == 'failed' else None, find({'queued'}), find({'starting', 'running'}), find({'completed', 'failed', 'cancelled'}), _active(group), _waiting(group, 'approval'), _waiting(group, 'limit'), 'unknown' if changed else 'estimated', group[0].cursor, group[-1].cursor))
    return result


def run_of_event(runs: list[RunInfo], cursor: int, ts) -> RunInfo | None:
    for run in runs:
        if run.first_cursor is not None and run.last_cursor is not None and run.first_cursor <= cursor <= run.last_cursor:
            return run
    return None
