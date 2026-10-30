"""Deterministic task-level efficiency aggregation."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from statistics import median
from sqlalchemy import select

from ..models import AccountProfile, AgentEvent, Session, Task
from ..system_settings import get_setting
from .usage import USAGE_EVENTS, normalize, parse_prices, price_of
from .observations import observations, task_warnings

from .runs import runs_for_sessions, run_of_event


def _role(value):
    return value if value in ('orchestrator', 'executor') else 'single'


def _blank():
    return {'tokens': 0, 'fresh_input': 0, 'cache_read': 0, 'cache_write': 0, 'output': 0,
                'cost': 0.0, 'unpriced': 0, 'events': 0}


def _add(bucket, tokens, cost):
    bucket['fresh_input'] += tokens['input']
    for k in ('cache_read', 'cache_write', 'output'):
        bucket[k] += tokens[k]
    n = sum(tokens.values())
    bucket['tokens'] += n
    bucket['events'] += 1
    if cost is None:
        bucket['unpriced'] += n
    else:
        bucket['cost'] += cost


def _cost(bucket):
    return None if not bucket['events'] or (bucket['unpriced'] and bucket['cost'] == 0) else bucket['cost']


def collect(db, days=30, project_id=None, model=None, account_id=None, role=None, status=None):
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    filters = {'days': days, 'project_id': project_id, 'model': model, 'account_id': account_id, 'role': role, 'status': status}
    sessions = list(db.scalars(select(Session)))
    tasks = {t.id: t for t in db.scalars(select(Task))}
    names = {a.id: a.name for a in db.scalars(select(AccountProfile))}
    prices = parse_prices(get_setting(db, 'model_prices'))
    runs = runs_for_sessions(db, [s.id for s in sessions]) if sessions else {}
    session_map = {s.id: s for s in sessions}
    # An orchestration child can inherit its parent task even when its own task_id is absent.
    def task_id(s, run=None):
        tid = getattr(run, 'task_id', None) or s.task_id
        parent = getattr(run, 'orchestration_id', None) or s.parent_session_id
        seen = set()
        while not tid and parent in session_map and parent not in seen:
            seen.add(parent)
            p = session_map[parent]
            tid, parent = p.task_id, p.parent_session_id
        return tid or 'session:' + s.id
    rows = {}
    run_records = {}
    participants = {}
    series = {}
    roles = {}
    triggers = {}
    total = _blank()
    continuation_tokens = 0
    matched_tasks = set()
    def allowed(s, run, tid):
        t = tasks.get(tid)
        return ((not project_id or (getattr(run, 'project_id', None) or s.project_id) == project_id)
                and (not model or getattr(run, 'model', None) == model)
                and (not account_id or getattr(run, 'account_profile_id', None) == account_id)
                and (not role or _role(getattr(run, 'role', None)) == role)
                and (not status or (t and t.status == status)))
    def row_for(tid, s):
        if tid not in rows:
            t = tasks.get(tid)
            rows[tid] = {'task_id': tid, 'title': t.title if t else (s.title or tid), 'project_id': t.project_id if t else s.project_id,
                             'status': t.status if t else None, 'updated': t.updated_at if t else s.updated_at,
                             'bucket': _blank(), 'sessions': set(), 'agents': set(), 'runs': [], 'role_buckets': {}}
        return rows[tid]
    for s in sessions:
        for run in runs.get(s.id, []):
            tid = task_id(s, run)
            if not allowed(s, run, tid):
                continue
            start = run.started_at or run.queued_at
            if since and (not start or start < since) and (not run.finished_at or run.finished_at < since):
                continue
            row = row_for(tid, s); row['sessions'].add(s.id); row['agents'].add(s.id); row['runs'].append(run)
            matched_tasks.add(tid)
            key = (s.id, run.run_index)
            run_records[key] = {'run': run, 'bucket': _blank()}
            p = participants.setdefault((tid, s.id), {'session': s, 'bucket': _blank(), 'runs': [], 'roles': set()})
            p['runs'].append(run); p['roles'].add(_role(run.role))
            trigger = run.trigger or 'unknown'
            triggers.setdefault(trigger, {'runs': 0, 'bucket': _blank()})['runs'] += 1
    events = db.scalars(select(AgentEvent).where(AgentEvent.kind.in_(['message', 'output'])).order_by(AgentEvent.cursor))
    for event in events:
        payload = event.payload or {}
        if payload.get('raw_type') not in USAGE_EVENTS or not isinstance(payload.get('usage'), dict):
            continue
        if since and event.ts < since:
            continue
        s = session_map.get(event.session_id)
        if not s:
            continue
        run = next((r for r in runs.get(s.id, []) if r.id and r.id == event.run_id), None)
        run = run or run_of_event(runs.get(s.id, []), event.cursor, event.ts)
        if not run:
            continue
        tid = task_id(s, run)
        if not allowed(s, run, tid):
            continue
        row = row_for(tid, s); row['sessions'].add(s.id); row['agents'].add(s.id); matched_tasks.add(tid)
        key = (s.id, run.run_index)
        if key not in run_records:
            run_records[key] = {'run': run, 'bucket': _blank()}; row['runs'].append(run)
            p = participants.setdefault((tid, s.id), {'session': s, 'bucket': _blank(), 'runs': [], 'roles': set()})
            p['runs'].append(run); p['roles'].add(_role(run.role))
            triggers.setdefault(run.trigger or 'unknown', {'runs': 0, 'bucket': _blank()})['runs'] += 1
        p = participants[(tid, s.id)]
        tokens = normalize(run.engine or s.engine or '', payload['usage'])
        value = payload.get('cost_usd')
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            value = price_of(tokens, prices[run.model]) if run.model in prices else None
            basis = ('price_table_approx_cache_write' if tokens['cache_write'] else 'price_table') if value is not None else 'unpriced'
        else:
            basis = 'engine'
        rec = run_records[key]; rec.setdefault('bases', set()).add(basis)
        r = _role(run.role); role_bucket = roles.setdefault(r, _blank())
        rb = row['role_buckets'].setdefault(r, _blank())
        day = event.ts.date()
        if days > 90 or days == 0:
            day -= timedelta(days=day.weekday())
        period = day.isoformat()
        sb = series.setdefault(period, {'bucket': _blank(), 'completed': set(), 'done_bucket': _blank()})
        for bucket in (total, row['bucket'], rec['bucket'], p['bucket'], role_bucket, rb, triggers[run.trigger or 'unknown']['bucket'], sb['bucket']):
            _add(bucket, tokens, value)
        if tasks.get(tid) and tasks[tid].status == 'done':
            _add(sb['done_bucket'], tokens, value)
        if run.trigger == 'continue':
            continuation_tokens += sum(tokens.values())
    # Tasks without sessions are visible when no participant filters are applied.
    if not any((model, account_id, role)):
        for t in tasks.values():
            if (not project_id or t.project_id == project_id) and (not status or t.status == status) and (not since or t.updated_at >= since) and t.id not in rows:
                rows[t.id] = {'task_id': t.id, 'title': t.title, 'project_id': t.project_id, 'status': t.status,
                                      'updated': t.updated_at, 'bucket': _blank(), 'sessions': set(), 'agents': set(), 'runs': [], 'role_buckets': {}}
    output = []
    for tid, row in rows.items():
        rr = row['runs']; starts = [r.started_at or r.queued_at for r in rr if r.started_at or r.queued_at]; ends = [r.finished_at for r in rr if r.finished_at]
        wall = (max(ends) - min(starts)).total_seconds() if starts and ends and max(ends) >= min(starts) else None
        active = [r.active_s for r in rr if r.active_s is not None]
        b = row['bucket']
        def role_out(name, role_buckets=row['role_buckets']):
            x = role_buckets.get(name, _blank()); return {'tokens': x['tokens'], 'cost_usd': _cost(x)}
        item = {'task_id': tid, 'title': row['title'], 'project_id': row['project_id'], 'status': row['status'], 'agents': len(row['agents']), 'sessions': len(row['sessions']), 'runs': len(rr), 'tokens': b['tokens'], 'fresh_input': b['fresh_input'], 'cache_read': b['cache_read'], 'cache_write': b['cache_write'], 'output': b['output'], 'cost_usd': _cost(b), 'cost_partial': bool(b['unpriced']), 'wall_s': wall, 'active_s': sum(active) if active else None, 'duration_basis': ('unknown' if wall is None else ('measured' if all(r.attribution == 'exact' for r in rr) else 'estimated')), 'retries': sum(r.trigger == 'retry_after_failure' for r in rr), 'orchestrator': role_out('orchestrator'), 'executors': role_out('executor')}
        output.append(item)
        if item['status'] == 'done':
            dt = row['updated'].date()
            if days > 90 or days == 0: dt -= timedelta(days=dt.weekday())
            series.setdefault(dt.isoformat(), {'bucket': _blank(), 'completed': set(), 'done_bucket': _blank()})['completed'].add(tid)
    completed = sum(x['status'] == 'done' for x in output)
    done_rows = [x for x in output if x['status'] == 'done']
    walls = [x['wall_s'] for x in done_rows if x['wall_s'] is not None]
    done_tokens = sum(x['tokens'] for x in done_rows)
    done_cost = sum(x['cost_usd'] or 0 for x in done_rows)
    done_unpriced = any(x['cost_partial'] for x in done_rows)
    done_priced = any(rows[x['task_id']]['bucket']['events'] and x['cost_usd'] is not None for x in done_rows)
    total_cost = total['cost']; orch = roles.get('orchestrator', _blank())
    obs = observations(output)
    kpi = {'completed_tasks': completed, 'tokens_per_completed_task': done_tokens/completed if completed and any(rows[x['task_id']]['bucket']['events'] for x in done_rows) else None,
               'cost_per_completed_task': done_cost/completed if completed and done_priced and not done_unpriced else None,
               'cost_partial': bool(total['unpriced']), 'median_wall_s': median(walls) if walls else None,
               'orchestrator_cost_share': orch['cost']/total_cost if total_cost and not total['unpriced'] else None,
               'orchestrator_cost_share_exact': all(r.attribution == 'exact' for row in rows.values() for r in row['runs']),
               'confirmed_retries': sum(x['retries'] for x in output), 'total_tokens': total['tokens'], 'total_cost_usd': total_cost,
               'unpriced_tokens': total['unpriced']}
    series_out = []
    for period, entry in sorted(series.items()):
        b = entry['bucket']; done = entry['done_bucket']; n = len(entry['completed'])
        series_out.append({'period': period, 'tokens': b['tokens'], 'cost_usd': b['cost'], 'cost_partial': bool(b['unpriced']), 'completed_tasks': n, 'cost_per_completed_task': done['cost']/n if n and done['events'] and not done['unpriced'] else None, 'tokens_per_completed_task': done['tokens']/n if n and done['events'] else None})
    by_role = [{'role': k, 'tokens': b['tokens'], 'cost_usd': b['cost'], 'cost_partial': bool(b['unpriced']), 'token_share': b['tokens']/total['tokens'] if total['tokens'] else 0.0, 'cost_share': b['cost']/total_cost if total_cost and not total['unpriced'] else None} for k,b in sorted(roles.items())]
    by_trigger = [{'trigger': k, 'runs': v['runs'], 'tokens': v['bucket']['tokens'], 'cost_usd': v['bucket']['cost'], 'cost_partial': bool(v['bucket']['unpriced'])} for k,v in sorted(triggers.items())]
    context = {'cache_read_share': total['cache_read']/total['tokens'] if total['tokens'] else None, 'fresh_to_cache_ratio': total['fresh_input']/total['cache_read'] if total['cache_read'] else None, 'compactions': None, 'continuation_tokens': continuation_tokens}
    return {'filters': filters, 'since': since, 'kpi': kpi, 'series': series_out, 'granularity': 'week' if days > 90 or days == 0 else 'day', 'by_role': by_role, 'by_trigger': by_trigger, 'context': context, 'observations': obs}, output, rows, participants, run_records, names


def detail(data, task_id):
    summary, items, rows, participants, records, names = data
    item = next((x for x in items if x['task_id'] == task_id), None)
    if not item: return None
    people = []
    for (tid, sid), p in sorted(participants.items()):
        if tid != task_id: continue
        s = p['session']; b = p['bucket']; rr = p['runs']; last = rr[-1]
        people.append({'session_id': sid, 'role': _role(last.role), 'engine': last.engine, 'model': last.model, 'account_id': last.account_profile_id, 'account_name': names.get(last.account_profile_id), 'status': s.status, 'tokens': b['tokens'], 'cost_usd': _cost(b), 'cost_partial': bool(b['unpriced']), 'runs': len(rr), 'retries': sum(r.trigger == 'retry_after_failure' for r in rr)})
    rr = []
    for run in rows[task_id]['runs']:
        rec = records[(run.session_id, run.run_index)]; b = rec['bucket']; bases = rec.get('bases', set())
        rr.append({**asdict(run), 'tokens': b['tokens'], 'cost_usd': _cost(b), 'cost_partial': bool(b['unpriced']), 'cost_basis': next(iter(bases)) if len(bases) == 1 else ('mixed' if bases else 'unpriced')})
    return {**item, 'participants': people, 'runs': rr, 'warnings': task_warnings(item, rr), 'observations': [o for o in summary['observations'] if o['subject'].get('task_id') == task_id]}
