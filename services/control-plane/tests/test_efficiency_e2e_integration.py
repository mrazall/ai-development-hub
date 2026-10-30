"""Cross-endpoint efficiency contract, using HTTP for the observable workflow."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from test_api_integration import admin_token, auth, clean_schema, client, make_project

pytestmark = pytest.mark.integration


def test_efficiency_contract(client, admin_token):  # noqa: F811
    from aihub_control.auth import hash_password
    from aihub_control.db import get_session_factory
    from aihub_control.models import AgentEvent, ExecutionRun, Session, User

    headers = auth(admin_token)
    make_project(client, admin_token)
    tasks = {}
    for status in ('done', 'review', 'failed'):
        response = client.post('/api/v0/projects/demo/tasks', headers=headers, json={'title': status})
        assert response.status_code == 200
        task = response.json()
        response = client.patch(f"/api/v0/projects/demo/tasks/{task['id']}", headers=headers, json={'title': status, 'status': status})
        assert response.status_code == 200
        tasks[status] = task['id']

    assert client.put('/api/v0/system/settings/model_prices', headers=headers,
                      json={'value': 'priced=1,0.1,10\nclaude=100,100,100'}).status_code == 200
    sessions = []
    for task, role, engine, model, payload in [
        ('done', 'orchestrator', 'claude_code', 'claude', {'raw_type': 'result', 'cost_usd': 1.5, 'usage': {'input_tokens': 100, 'cache_read_input_tokens': 1000, 'cache_creation_input_tokens': 50, 'output_tokens': 200}}),
        ('done', 'executor', 'codex', 'priced', {'raw_type': 'turn.completed', 'usage': {'input_tokens': 1000000, 'cached_input_tokens': 600000, 'output_tokens': 100000}}),
        ('review', 'executor', 'claude_code', 'unknown-model', {'raw_type': 'result', 'usage': {'input_tokens': 20, 'cache_read_input_tokens': 10, 'cache_creation_input_tokens': 5, 'output_tokens': 15}}),
        ('failed', 'executor', 'codex', 'unknown-model', {'raw_type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 20}}),
    ]:
        response = client.post('/api/v0/sessions', headers=headers, json={'project_id': 'demo', 'worker_id': 'worker-a', 'task_id': tasks[task], 'engine': engine, 'provider': 'test', 'model': model, 'auth_mode': 'subscription', 'workdir': '/tmp/project'})
        assert response.status_code == 200
        sid = response.json()['id']
        event = {'kind': 'message', 'client_event_id': 'usage-1', 'payload': payload}
        first = client.post(f'/api/v0/sessions/{sid}/events', headers=headers, json=[event])
        duplicate = client.post(f'/api/v0/sessions/{sid}/events', headers=headers, json=[event])
        assert first.status_code == duplicate.status_code == 200
        assert first.json()[0]['cursor'] == duplicate.json()[0]['cursor']
        sessions.append((sid, task, role, engine, model, first.json()[0]['cursor']))

    # Lifecycle is populated directly so this API test does not depend on a live worker.
    # Each usage event is tied to the exact run, with one retry and one auto-resume.
    _, factory = get_session_factory()
    db = factory()
    now = datetime.now(timezone.utc)
    for sid, task, role, engine, model, cursor in sessions:
        session = db.get(Session, sid)
        session.role = role
        run = db.query(ExecutionRun).filter_by(session_id=sid, run_index=1).one()
        run.engine, run.model, run.role = engine, model, role
        run.orchestration_id = sessions[0][0]
        run.trigger = 'initial'
        run.status = 'failed' if task == 'failed' else 'completed'
        run.attribution = 'exact'
        run.queued_at = now - timedelta(seconds=120)
        run.started_at = now - timedelta(seconds=100)
        run.finished_at = now - timedelta(seconds=60)
        db.get(AgentEvent, cursor).run_id = run.id
        if task == 'failed':
            for run_index, trigger in ((2, 'retry_after_failure'), (3, 'auto_resume')):
                db.add(ExecutionRun(id=str(uuid4()), session_id=sid, task_id=tasks[task], project_id='demo', run_index=run_index, engine=engine, model=model, role=role, orchestration_id=sessions[0][0], trigger=trigger, status='completed', attribution='exact', started_at=now - timedelta(seconds=50 - run_index), finished_at=now - timedelta(seconds=10 - run_index)))
    db.add(User(username='viewer', password_hash=hash_password('viewer-password'), role='viewer'))
    db.commit()
    db.close()

    def get(path, params=None):
        response = client.get(path, headers=headers, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    summary = get('/api/v0/stats/efficiency', {'days': 0, 'project_id': 'demo'})
    kpi = summary['kpi']
    assert kpi['completed_tasks'] == 1
    assert kpi['total_tokens'] == 1101520
    assert kpi['tokens_per_completed_task'] == 1101350
    assert kpi['cost_per_completed_task'] == pytest.approx(2.96)
    assert kpi['total_cost_usd'] == pytest.approx(2.96)
    assert kpi['unpriced_tokens'] == 170
    assert kpi['cost_partial'] is True
    assert kpi['confirmed_retries'] == 1
    assert sum(row['tokens'] for row in summary['by_role']) == kpi['total_tokens']
    triggers = {row['trigger']: row for row in summary['by_trigger']}
    assert triggers['retry_after_failure']['runs'] == 1
    assert triggers['auto_resume']['runs'] == 1
    rows = []
    offset = 0
    while True:
        page = get('/api/v0/stats/tasks', {'days': 0, 'project_id': 'demo', 'limit': 1, 'offset': offset})
        rows.extend(page['items'])
        offset += len(page['items'])
        if offset >= page['total']:
            break
        assert page['items']
    assert sum(row['tokens'] for row in rows) == kpi['total_tokens']
    assert {row['task_id'] for row in rows} == set(tasks.values())
    detail = get(f"/api/v0/stats/tasks/{tasks['done']}", {'days': 0})
    assert detail['tokens'] == 1101350
    assert detail['cost_usd'] == pytest.approx(2.96)
    assert detail['wall_s'] == pytest.approx(40)
    assert detail['duration_basis'] == 'measured'
    assert {run['attribution'] for run in detail['runs']} == {'exact'}
    assert get(f"/api/v0/stats/tasks/{tasks['failed']}", {'days': 0})['retries'] == 1
    assert {p['role'] for p in detail['participants']} == {'orchestrator', 'executor'}
    filtered = get('/api/v0/stats/efficiency', {'days': 0, 'project_id': 'demo', 'status': 'review'})
    assert filtered['kpi']['completed_tasks'] == 0
    assert filtered['kpi']['tokens_per_completed_task'] is None
    assert filtered['kpi']['cost_per_completed_task'] is None
    assert filtered['kpi']['total_tokens'] == 50
    assert get('/api/v0/stats/efficiency', {'days': 0, 'model': 'priced'})['kpi']['total_tokens'] == 1100000
    assert get('/api/v0/stats/efficiency', {'days': 0, 'role': 'orchestrator'})['kpi']['total_tokens'] == 1350
    assert client.get('/api/v0/stats/tasks/missing', headers=headers).status_code == 404
    viewer = client.post('/api/v0/auth/login', json={'username': 'viewer', 'password': 'viewer-password'}).json()['access_token']
    for path in ('/api/v0/stats/efficiency', '/api/v0/stats/tasks', f"/api/v0/stats/tasks/{tasks['done']}"):
        assert client.get(path, headers=auth(viewer)).status_code == 403
