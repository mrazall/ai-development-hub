import pytest
from aihub_control.state import validate_transition


def test_valid_session_transition():
    validate_transition("queued", "starting")


def test_invalid_session_transition():
    with pytest.raises(ValueError):
        validate_transition("completed", "running")


def test_offline_can_reconnect():
    validate_transition("offline", "starting")


def test_offline_session_can_still_complete():
    validate_transition("offline", "completed")
