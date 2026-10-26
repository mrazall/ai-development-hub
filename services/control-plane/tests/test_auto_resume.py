from datetime import datetime, timezone

from aihub_control.orchestration.auto_resume import is_limit_message, parse_reset

NOW = datetime(2026, 10, 25, 18, 24, tzinfo=timezone.utc)  # 21:24 in Moscow


def test_detects_provider_limit_messages():
    assert is_limit_message("You've hit your session limit · resets 12am (Europe/Moscow)")
    assert is_limit_message("You've hit your usage limit. Try again later.")
    assert not is_limit_message("Готово: тесты прошли")


def test_reset_is_the_next_occurrence_in_the_given_zone():
    assert parse_reset("resets 12am (Europe/Moscow)", NOW) == datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
    assert parse_reset("resets 3:30pm (Europe/Moscow)", NOW) == datetime(2026, 10, 26, 12, 30, tzinfo=timezone.utc)
    assert parse_reset("resets 11pm (UTC)", NOW) == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)
    assert parse_reset("no time here", NOW) is None
