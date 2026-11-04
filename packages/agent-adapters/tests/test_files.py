import base64

import pytest

from aihub_agents.files import MAX_BYTES, FilesError, handle


@pytest.fixture
def workdir(tmp_path):
    root = tmp_path / "work"
    (root / ".aihub" / "share").mkdir(parents=True)
    (root / ".aihub" / "share" / "shot.png").write_bytes(b"\x89PNG fake")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hi')\n")
    (root / ".git").mkdir()
    (root / "node_modules").mkdir()
    return root


def test_listing_shows_the_share_folder_and_hides_noise(workdir):
    listed = handle({"op": "list", "workdir": str(workdir)})
    assert listed["share"] == ".aihub/share"
    names = [entry["name"] for entry in listed["entries"]]
    assert names == [".aihub", "src"]  # folders first; .git and node_modules are not offered
    share = handle({"op": "list", "path": ".aihub/share", "workdir": str(workdir)})
    assert share["entries"][0]["path"] == ".aihub/share/shot.png" and share["entries"][0]["size"] == 9


def test_a_file_comes_back_whole_with_its_type(workdir):
    shot = handle({"op": "read", "path": ".aihub/share/shot.png", "workdir": str(workdir)})
    assert shot["mime"] == "image/png" and base64.b64decode(shot["base64"]) == b"\x89PNG fake"


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "src/../../outside.txt"])
def test_nothing_outside_the_workdir(workdir, path):
    (workdir.parent / "outside.txt").write_text("secret")
    with pytest.raises(FilesError):
        handle({"op": "read", "path": path, "workdir": str(workdir)})


def test_links_out_of_the_workdir_are_neither_listed_nor_read(workdir):
    (workdir.parent / "secret.txt").write_text("secret")
    (workdir / "link.txt").symlink_to(workdir.parent / "secret.txt")
    assert "link.txt" not in [e["name"] for e in handle({"op": "list", "workdir": str(workdir)})["entries"]]
    with pytest.raises(FilesError):
        handle({"op": "read", "path": "link.txt", "workdir": str(workdir)})


def test_big_files_are_refused(workdir):
    (workdir / "big.bin").write_bytes(b"0" * (MAX_BYTES + 1))
    with pytest.raises(FilesError, match="МБ"):
        handle({"op": "read", "path": "big.bin", "workdir": str(workdir)})


def test_an_absolute_path_inside_the_folder_works(workdir):
    listed = handle({"op": "list", "path": str(workdir / ".aihub" / "share"), "workdir": str(workdir)})
    assert listed["path"] == ".aihub/share"
