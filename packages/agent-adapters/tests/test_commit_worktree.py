import subprocess
import sys

import pytest

from aihub_agents.workspace import commit_worktree

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="git worktree paths are POSIX on the worker")


def test_commit_worktree_commits_changes_once(tmp_path):
    git = lambda *args: subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("1")
    git("add", "-A")
    git("commit", "-qm", "base")
    assert commit_worktree(str(tmp_path), "nothing") is None
    (tmp_path / "a.txt").write_text("2")
    (tmp_path / "b.txt").write_text("new")
    sha = commit_worktree(str(tmp_path), "Executor work")
    assert sha and git("log", "-1", "--format=%s").stdout.strip() == "Executor work"
    assert git("status", "--porcelain").stdout == ""
