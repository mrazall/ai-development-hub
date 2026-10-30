from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aihub_control.analytics.runs import _active, _waiting, run_of_event
from aihub_control.models import AgentEvent, ExecutionRun


def test_running_intervals_exclude_approval_wait():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [SimpleNamespace(kind='session.status', ts=start + timedelta(seconds=t), payload={'status': status})
              for t, status in [(0, 'running'), (10, 'waiting_approval'), (30, 'running'), (35, 'completed')]]
    assert _active(events) == 15


def test_cursor_selects_run():
    first = SimpleNamespace(first_cursor=10, last_cursor=15)
    second = SimpleNamespace(first_cursor=16, last_cursor=20)
    assert run_of_event([first, second], 17, None) is second
    assert run_of_event([first, second], 21, None) is None


def test_model_has_run_identity_and_unique_index():
    assert AgentEvent.__table__.c.run_id.type.length == 36
    assert any({c.name for c in constraint.columns} == {'session_id', 'run_index'}
               for constraint in ExecutionRun.__table__.constraints if hasattr(constraint, 'columns'))


def test_waiting_intervals_require_closed_observations():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def events(items):
        return [SimpleNamespace(kind='session.status', ts=start + timedelta(seconds=t),
                                payload={'status': status}) for t, status in items]
    history = events([(0, 'running'), (10, 'waiting_approval'), (15, 'waiting_approval'),
                      (30, 'running'), (40, 'waiting_limit'), (55, 'running'),
                      (60, 'waiting_limit')])
    assert _waiting(history, 'approval') == 20
    assert _waiting(history, 'limit') == 15
    assert _waiting(events([(0, 'running'), (1, 'waiting_limit')]), 'limit') is None
    assert _waiting(events([(0, 'running'), (1, 'completed')]), 'approval') is None
