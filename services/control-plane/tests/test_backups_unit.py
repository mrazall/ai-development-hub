from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aihub_control.backups.parser import latest_by_kind, parse_restic_json, rpo_exceeded


def test_parse_restic_json_uses_last_json_record():
    parsed = parse_restic_json('progress\n{"message_type":"status"}\n{"message_type":"summary","snapshot_id":"abc123"}\n')
    assert parsed == {"message_type": "summary", "snapshot_id": "abc123"}


def test_parse_restic_json_rejects_non_json():
    with pytest.raises(ValueError):
        parse_restic_json("restic failed\n")


def test_rpo_marks_missing_or_old_database_snapshot():
    now = datetime.now(timezone.utc)
    fresh = SimpleNamespace(ok=True, finished_at=now - timedelta(hours=5))
    old = SimpleNamespace(ok=True, finished_at=now - timedelta(hours=7))
    assert not rpo_exceeded(fresh, now=now, rpo_seconds=6 * 60 * 60)
    assert rpo_exceeded(old, now=now, rpo_seconds=6 * 60 * 60)
    assert rpo_exceeded(None, now=now, rpo_seconds=6 * 60 * 60)


def test_latest_by_kind():
    first = SimpleNamespace(kind="database", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    second = SimpleNamespace(kind="database", started_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    config = SimpleNamespace(kind="config", started_at=first.started_at)
    assert latest_by_kind([first, second, config]) == {"database": second, "config": config}
