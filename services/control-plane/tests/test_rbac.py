from unittest.mock import Mock
from aihub_control.rbac import can_access_project


def test_admin_access():
    db = Mock()
    db.get.return_value = Mock(visibility="private")
    user = Mock(role="admin")
    assert can_access_project(db, user, "p")


def test_shared_access_for_viewer():
    db = Mock()
    db.get.return_value = Mock(visibility="shared")
    user = Mock(role="viewer")
    assert can_access_project(db, user, "p")
