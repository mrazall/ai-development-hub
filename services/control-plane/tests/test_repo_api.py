# ruff: noqa: F811
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from aihub_control.db import get_session_factory
from aihub_control.models import Notification, Project, ProjectMember, RepoCache, Session, User, Worker, WorkerRequest, now
from aihub_control.routers.repo import finish_repo_request
from test_api_integration import admin_token, auth, clean_schema, client, make_project

pytestmark = pytest.mark.integration


def test_cache_refresh_and_validation(client, admin_token, clean_schema):
    make_project(client, admin_token)
    _, factory = get_session_factory()
    with factory() as db:
        project = db.get(__import__("aihub_control.models", fromlist=["Project"]).Project, "demo")
        project.allowed_paths = ["/tmp/repo"]
        db.add(Worker(id="repo-worker", host="local", kind="local", status="online"))
        db.add(RepoCache(project_id="demo", kind="graph", worker_id="repo-worker", fetched_at=now() - timedelta(seconds=90), payload={"base": "main", "branches": [], "commits": []}))
        db.commit()
    response = client.get("/api/v0/projects/demo/repo/graph", headers=auth(admin_token))
    assert response.json()["fetched_at"] and response.json()["refreshing"]
    client.get("/api/v0/projects/demo/repo/graph", headers=auth(admin_token))
    with factory() as db:
        requests = db.scalars(select(WorkerRequest).where(WorkerRequest.kind == "repo_graph")).all()
        assert len(requests) == 1 and requests[0].response == {"project_id": "demo", "limit": 200}
    for action, target, confirm in [("delete_branch", "main", True), ("unknown", "1", True), ("merge_pr", "1", False)]:
        assert client.post("/api/v0/projects/demo/repo/actions", headers=auth(admin_token), json={"action": action, "target": target, "confirm": confirm}).status_code == 422
    assert client.get("/api/v0/projects/unknown/repo/graph", headers=auth(admin_token)).status_code == 404


def test_worker_result_and_notifications(client, admin_token, clean_schema):
    make_project(client, admin_token)
    _, factory = get_session_factory()
    with factory() as db:
        db.add(RepoCache(project_id="demo", kind="graph", payload={"base": "main"}, fetched_at=now()))
        db.add(RepoCache(project_id="demo", kind="github", payload={"runs": [{"workflow": "test", "branch": "main", "status": "completed", "conclusion": "success"}], "pulls": []}, fetched_at=now()))
        db.flush()
        request = WorkerRequest(worker_id="worker", kind="repo_github", response={"project_id": "demo"})
        result = {"result": {"available": True, "runs": [{"workflow": "test", "branch": "main", "status": "completed", "conclusion": "failure"}], "pulls": [{"number": 1, "draft": False, "mergeable": True, "checks": {"state": "success"}}]}}
        finish_repo_request(db, request, result)
        db.flush()
        assert db.get(RepoCache, ("demo", "github")).payload == result["result"]
        assert len(db.scalars(select(Notification)).all()) == 2
        finish_repo_request(db, request, result)
        db.flush()
        assert len(db.scalars(select(Notification)).all()) == 2


@pytest.mark.parametrize('visibility', ['private', 'shared', 'public'])
def test_repo_notifications_follow_project_access(client, admin_token, clean_schema, visibility):
    make_project(client, admin_token)
    _, factory = get_session_factory()
    with factory() as db:
        project = db.get(Project, 'demo')
        project.visibility = visibility
        member = User(username='member', password_hash='unused', role='viewer')
        outsider = User(username='outsider', password_hash='unused', role='viewer')
        db.add_all([member, outsider])
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=member.id))
        db.add_all([
            RepoCache(project_id=project.id, kind='graph', payload={'base': 'main'}, fetched_at=now()),
            RepoCache(project_id=project.id, kind='github', fetched_at=now(), payload={
                'runs': [{'workflow': 'test', 'branch': 'main', 'status': 'completed', 'conclusion': 'success'}],
                'pulls': [],
            }),
        ])
        db.flush()
        finish_repo_request(db, WorkerRequest(kind='repo_action', response={'project_id': project.id}), {'result': {}})
        finish_repo_request(db, WorkerRequest(kind='repo_github', response={'project_id': project.id}), {'result': {
            'runs': [{'workflow': 'test', 'branch': 'main', 'status': 'completed', 'conclusion': 'failure'}],
            'pulls': [{'number': 1, 'mergeable': True, 'checks': {'state': 'success'}}],
        }})
        notifications = db.scalars(select(Notification)).all()
        admin = db.scalar(select(User).where(User.username == 'admin'))
        expected = {member.id, admin.id}
        if visibility != 'private':
            expected.add(outsider.id)
        for category in ('repo.action', 'repo.ci', 'repo.pr'):
            assert {n.user_id for n in notifications if n.category == category} == expected


def setup_repo(client, token):
    make_project(client, token)
    worker = client.post('/api/v0/workers', headers=auth(token), json={
        'id': 'worker-a', 'host': 'local', 'kind': 'linux',
    }).json()
    _, factory = get_session_factory()
    with factory() as db:
        db.get(Project, 'demo').allowed_paths = ['/tmp/repository', '/tmp/other']
        db.get(Worker, 'worker-a').status = 'online'
        db.commit()
    return worker, factory


def reply(client, worker, request_id, payload):
    response = client.post(f"/api/v0/workers/worker-a/requests/{request_id}/response",
                           headers=auth(worker['worker_token']), json=payload)
    assert response.status_code == 200


def test_action_permissions_and_validation(client, admin_token, clean_schema):
    from aihub_control.auth import hash_password
    from aihub_control.models import ProjectMember, User

    _, factory = setup_repo(client, admin_token)
    make_project(client, admin_token, 'private-other')
    with factory() as db:
        viewer = User(username='repo-viewer', password_hash=hash_password('password'), role='viewer')
        db.add(viewer)
        db.flush()
        db.add(ProjectMember(project_id='demo', user_id=viewer.id))
        admin = db.scalar(select(User).where(User.username == 'admin'))
        db.add(ProjectMember(project_id='demo', user_id=admin.id))
        db.commit()
    viewer = client.post('/api/v0/auth/login', json={'username': 'repo-viewer', 'password': 'password'}).json()['access_token']
    data = {'action': 'merge_pr', 'target': '12', 'confirm': True}
    assert client.post('/api/v0/projects/demo/repo/actions', headers=auth(viewer), json=data).status_code == 403
    response = client.post('/api/v0/projects/demo/repo/actions', headers=auth(admin_token), json=data)
    assert response.status_code == 202
    with factory() as db:
        request = db.get(WorkerRequest, response.json()['request_id'])
        assert request.kind == 'repo_action'
        assert request.response == {'project_id': 'demo', 'action': 'merge_pr', 'target': '12'}
    for data in [
        {'action': 'delete_branch', 'target': 'main', 'confirm': True},
        {'action': 'merge_pr', 'target': '12', 'confirm': False},
        {'action': 'merge_pr', 'target': 'abc', 'confirm': True},
    ]:
        assert client.post('/api/v0/projects/demo/repo/actions', headers=auth(admin_token), json=data).status_code == 422
    assert client.post('/api/v0/projects/unknown/repo/actions', headers=auth(admin_token), json=data).status_code == 404
    # A viewer cannot write at all; verify isolation on a read of another private project.
    assert client.get('/api/v0/projects/private-other/repo/graph', headers=auth(viewer)).status_code == 404


def test_worker_priority(client, admin_token, clean_schema):
    _, factory = setup_repo(client, admin_token)
    with factory() as db:
        db.add(Worker(id='worker-b', host='local', kind='linux', status='online'))
        db.add(Worker(id='worker-c', host='local', kind='linux', status='online'))
        db.add(Session(project_id='demo', worker_id='worker-c', engine='codex', provider='openai',
                       model='test', auth_mode='subscription', workdir='/tmp/repository'))
        db.add(RepoCache(project_id='demo', kind='graph', worker_id='worker-b',
                         fetched_at=now(), payload={'base': 'main'}))
        db.commit()
    data = {'action': 'merge_pr', 'target': '1', 'confirm': True}
    def selected():
        response = client.post('/api/v0/projects/demo/repo/actions', headers=auth(admin_token), json=data)
        assert response.status_code == 202
        with factory() as db:
            return db.get(WorkerRequest, response.json()['request_id']).worker_id
    assert selected() == 'worker-c'
    with factory() as db:
        db.get(Worker, 'worker-c').status = 'offline'
        db.commit()
    assert selected() == 'worker-b'
    with factory() as db:
        db.get(RepoCache, ('demo', 'graph')).worker_id = None
        db.commit()
    assert selected() == 'worker-a'


def test_graph_worker_roundtrip_and_missing_repository(client, admin_token, clean_schema):
    worker, factory = setup_repo(client, admin_token)
    with factory() as db:
        session = Session(project_id='demo', worker_id='worker-a', engine='codex', provider='openai',
                          model='test', auth_mode='subscription', workdir='/tmp/repository',
                          branch='aihub/session', title='My session')
        db.add(session)
        db.commit()
        session_id = session.id
    url = '/api/v0/projects/demo/repo/graph?limit=17'
    initial = client.get(url, headers=auth(admin_token)).json()
    assert initial['refreshing'] is True and initial['fetched_at'] is None
    pending = client.get('/api/v0/workers/worker-a/requests/next', headers=auth(worker['worker_token'])).json()
    assert pending['kind'] == 'repo_graph'
    assert pending['response'] == {'project_id': 'demo', 'limit': 17}
    assert pending['path'] == pending['workdir'] == '/tmp/repository'
    branches = [{'name': 'origin/aihub/session', 'head': 'abcdef1', 'is_remote': True, 'merged': False}]
    commits = [{'sha': 'abcdef1', 'parents': [], 'subject': 'First', 'author': 'A', 'at': '2026-01-01T00:00:00Z', 'refs': []}]
    reply(client, worker, pending['id'], {'result': {'base': 'main', 'branches': branches, 'commits': commits}})
    start = time.monotonic()
    response = client.get(url, headers=auth(admin_token))
    assert time.monotonic() - start < 0.1
    graph = response.json()
    assert graph['fetched_at'] is not None and graph['refreshing'] is False
    assert graph['commits'] == commits
    assert graph['branches'] == [{**branches[0], 'agent_session_id': session_id, 'agent_session_title': 'My session'}]
    with factory() as db:
        db.get(RepoCache, ('demo', 'graph')).fetched_at = now() - timedelta(seconds=90)
        db.commit()
    client.get(url, headers=auth(admin_token))
    pending = client.get('/api/v0/workers/worker-a/requests/next', headers=auth(worker['worker_token'])).json()
    reply(client, worker, pending['id'], {'error': 'fatal: not a git repository'})
    graph = client.get(url, headers=auth(admin_token)).json()
    assert graph['available'] is False
    assert graph['reason'] == "Repository not found on the project's workers"


def test_commit_request(client, admin_token, clean_schema):
    _, factory = setup_repo(client, admin_token)
    assert client.get('/api/v0/projects/demo/repo/commits/zzz', headers=auth(admin_token)).status_code == 422
    sha = 'abcdef1234567'
    response = client.get(f'/api/v0/projects/demo/repo/commits/{sha}', headers=auth(admin_token))
    assert response.status_code == 200 and response.json()['refreshing'] is True
    with factory() as db:
        request = db.scalar(select(WorkerRequest).where(WorkerRequest.kind == 'repo_commit'))
        assert request.response == {'project_id': 'demo', 'sha': sha}


def test_secret_redaction_and_ci_transitions(client, admin_token, clean_schema):
    worker, factory = setup_repo(client, admin_token)
    token = 'ghp_testSecret123'
    client.get('/api/v0/projects/demo/repo/graph', headers=auth(admin_token))
    pending = client.get('/api/v0/workers/worker-a/requests/next', headers=auth(worker['worker_token'])).json()
    reply(client, worker, pending['id'], {'result': {'base': 'main', 'branches': [], 'commits': [{'subject': token}]}})
    assert token not in client.get('/api/v0/projects/demo/repo/graph', headers=auth(admin_token)).text
    with factory() as db:
        db.get(RepoCache, ('demo', 'graph')).fetched_at = now() - timedelta(seconds=90)
        db.commit()
    client.get('/api/v0/projects/demo/repo/graph', headers=auth(admin_token))
    pending = client.get('/api/v0/workers/worker-a/requests/next', headers=auth(worker['worker_token'])).json()
    reply(client, worker, pending['id'], {'error': f'worker error {token}'})
    assert token not in client.get('/api/v0/projects/demo/repo/graph', headers=auth(admin_token)).text
    action = client.post('/api/v0/projects/demo/repo/actions', headers=auth(admin_token),
                         json={'action': 'merge_pr', 'target': '12', 'confirm': True}).json()
    reply(client, worker, action['request_id'], {'error': f'failed {token}'})
    with factory() as db:
        cache = db.get(RepoCache, ('demo', 'graph'))
        assert token not in str(cache.payload) and token not in cache.error
        notification = db.scalar(select(Notification).where(Notification.category == 'repo.action'))
        assert notification.severity == 'error' and token not in notification.body
        db.add(RepoCache(project_id='demo', kind='github', fetched_at=now(), payload={
            'runs': [{'workflow': 'tests', 'branch': 'main', 'status': 'completed', 'conclusion': 'success'}], 'pulls': []}))
        db.commit()
    def github_result(conclusion):
        with factory() as db:
            request = WorkerRequest(worker_id='worker-a', kind='repo_github', response={'project_id': 'demo'})
            db.add(request)
            db.commit()
            request_id = request.id
        reply(client, worker, request_id, {'result': {'runs': [{'workflow': 'tests', 'branch': 'main',
            'status': 'completed', 'conclusion': conclusion}], 'pulls': []}})
    github_result('failure')
    github_result('failure')
    with factory() as db:
        notifications = db.scalars(select(Notification).where(Notification.category == 'repo.ci')).all()
        assert [n.title for n in notifications] == ['CI failed on main: tests']
    github_result('success')
    with factory() as db:
        notifications = db.scalars(select(Notification).where(Notification.category == 'repo.ci').order_by(Notification.created_at)).all()
        assert [n.title for n in notifications] == ['CI failed on main: tests', 'CI fixed on main']
