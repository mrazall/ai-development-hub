import pytest

from aihub_agents.workspace import make_project_dir


def test_mkdir_creates_inside_allowed_root(tmp_path):
    result = make_project_dir(str(tmp_path / "projects" / "demo"), [str(tmp_path / "projects")])
    assert result["created"] is True
    assert (tmp_path / "projects" / "demo").is_dir()


def test_mkdir_existing_dir_is_ok(tmp_path):
    (tmp_path / "demo").mkdir()
    result = make_project_dir(str(tmp_path / "demo"), [str(tmp_path)])
    assert result == {"created": False, "path": str((tmp_path / "demo").resolve())}


@pytest.mark.parametrize("path", ["{root}/../outside", "{root}/sub/../../escape", "{root}"])
def test_mkdir_rejects_outside_root(tmp_path, path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        make_project_dir(path.format(root=root), [str(root)])
    assert not (tmp_path / "outside").exists() and not (tmp_path / "escape").exists()
