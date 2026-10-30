"""Efficiency aggregation and authorization regression coverage."""
import pytest

import test_api_integration as fixtures
from test_api_integration import auth, make_project

admin_token = fixtures.admin_token
clean_schema = fixtures.clean_schema
client = fixtures.client
from test_stats_integration import _session

pytestmark = pytest.mark.integration


def test_efficiency_usage_and_filters(client, admin_token):
    make_project(client, admin_token)
    codex = _session(client, admin_token, 'codex', 'unpriced-model')
    claude = _session(client, admin_token, 'claude_code', 'claude-model')
    for sid, payload in [(codex, {'raw_type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 10}}),
                         (claude, {'raw_type': 'result', 'cost_usd': 2, 'usage': {'input_tokens': 10, 'cache_read_input_tokens': 20, 'cache_creation_input_tokens': 5, 'output_tokens': 5}})]:
        response = client.post(f'/api/v0/sessions/{sid}/events', headers=auth(admin_token), json=[{'kind': 'message', 'payload': payload}])
        assert response.status_code == 200
    url = '/api/v0/stats/efficiency?days=0'
    result = client.get(url, headers=auth(admin_token)).json()
    assert result['kpi']['total_tokens'] == 150
    assert result['kpi']['total_cost_usd'] == 2
    assert result['kpi']['unpriced_tokens'] == 110
    assert result['kpi']['cost_partial'] is True
    assert result['kpi']['tokens_per_completed_task'] is None
    items = client.get('/api/v0/stats/tasks?days=0&limit=1', headers=auth(admin_token)).json()
    second = client.get('/api/v0/stats/tasks?days=0&limit=1&offset=1', headers=auth(admin_token)).json()
    assert sum(x['tokens'] for x in items['items'] + second['items']) == result['kpi']['total_tokens']
    assert sum(x['tokens'] for x in result['by_role']) == result['kpi']['total_tokens']
    assert client.get(url + '&model=claude-model', headers=auth(admin_token)).json()['kpi']['total_tokens'] == 40
    detail = client.get('/api/v0/stats/tasks/session:' + claude + '?days=0', headers=auth(admin_token)).json()
    assert detail['cost_usd'] == 2 and detail['runs'][0]['cost_basis'] == 'engine'
    assert client.get('/api/v0/stats/tasks/missing?days=0', headers=auth(admin_token)).status_code == 404


def test_efficiency_admin_only(client, admin_token):
    from aihub_control.auth import hash_password
    from aihub_control.db import get_session_factory
    from aihub_control.models import User
    _, factory = get_session_factory()
    with factory() as db:
        db.add(User(username='viewer', password_hash=hash_password('viewer-password'), role='viewer'))
        db.commit()
    token = client.post('/api/v0/auth/login', json={'username': 'viewer', 'password': 'viewer-password'}).json()['access_token']
    for path in ('efficiency', 'tasks', 'tasks/missing'):
        assert client.get('/api/v0/stats/' + path, headers=auth(token)).status_code == 403


def test_efficiency_cache_follows_new_events(client, admin_token):
    make_project(client, admin_token)
    sid = _session(client, admin_token, 'claude_code', 'claude-model')
    usage = {'raw_type': 'result', 'cost_usd': 1, 'usage': {'input_tokens': 10, 'output_tokens': 5}}
    client.post(f'/api/v0/sessions/{sid}/events', headers=auth(admin_token), json=[{'kind': 'message', 'payload': usage}])
    url = '/api/v0/stats/efficiency?days=0'
    first = client.get(url, headers=auth(admin_token)).json()['kpi']['total_tokens']
    assert client.get(url, headers=auth(admin_token)).json()['kpi']['total_tokens'] == first  # served again
    client.post(f'/api/v0/sessions/{sid}/events', headers=auth(admin_token), json=[{'kind': 'message', 'payload': usage}])
    # A new event changes the fingerprint: the cached result is not served stale.
    assert client.get(url, headers=auth(admin_token)).json()['kpi']['total_tokens'] == first + 15
