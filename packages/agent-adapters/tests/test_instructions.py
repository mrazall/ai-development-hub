import hashlib
import subprocess

import pytest

from aihub_agents.instructions import InstructionError, KEEP_BACKUPS, handle


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    (root / "AGENTS.md").write_text("old\n")
    (root / "notes.txt").write_text("other\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "shared-skill").mkdir(parents=True)
    (home / ".claude" / "skills" / "shared-skill" / "SKILL.md").write_text("shared\n")
    (home / ".claude" / "CLAUDE.md").write_text("global\n")
    # One profile links to the shared ~/.claude (as after the migration), another keeps its own files.
    linked = home / ".aihub" / "accounts" / "claude-main" / "claude"
    linked.mkdir(parents=True)
    (linked / "CLAUDE.md").symlink_to(home / ".claude" / "CLAUDE.md")
    (linked / "skills").symlink_to(home / ".claude" / "skills")
    own = home / ".aihub" / "accounts" / "claude-own" / "claude"
    (own / "skills" / "mine").mkdir(parents=True)
    (own / "skills" / "mine" / "SKILL.md").write_text("mine\n")
    (own / "skills" / "synced" / "bucket" / "docx").mkdir(parents=True)  # claude.ai sync: never offered
    return home


def test_project_files_are_listed_read_and_committed_alone(project, home):
    listed = handle({"op": "list", "scope": "project", "project_root": str(project)}, home)
    assert [f["path"] for f in listed["files"]] == ["AGENTS.md", "CLAUDE.md"] and listed["git"] is True
    agents = handle({"op": "read", "scope": "project", "path": "AGENTS.md", "project_root": str(project)}, home)
    assert agents["content"] == "old\n" and agents["readers"] == ["codex"]
    (project / "notes.txt").write_text("unrelated edit\n")  # someone else's change stays out of the commit
    result = handle({"op": "write", "scope": "project", "path": "AGENTS.md", "content": "new\n",
                     "base_sha256": agents["sha256"], "project_root": str(project)}, home)
    assert result["commit"] and result["snapshot"] is None
    assert git(project, "show", "--name-only", "--format=%s", "HEAD").splitlines() == [
        "docs: инструкции агентов (из панели): AGENTS.md", "", "AGENTS.md"]
    assert git(project, "status", "--porcelain") == "M notes.txt"


def test_owner_edits_get_their_own_commit_first(project, home):
    (project / "AGENTS.md").write_text("owner's edit\n")
    handle({"op": "write", "scope": "project", "path": "AGENTS.md", "content": "panel\n",
            "base_sha256": sha("owner's edit\n"), "project_root": str(project)}, home)
    subjects = git(project, "log", "--format=%s", "-3").splitlines()
    assert subjects[:2] == ["docs: инструкции агентов (из панели): AGENTS.md",
                            "snapshot: правки владельца перед правкой из панели"]


def test_a_changed_file_is_not_overwritten(project, home):
    with pytest.raises(InstructionError, match="conflict"):
        handle({"op": "write", "scope": "project", "path": "AGENTS.md", "content": "x",
                "base_sha256": sha("something else"), "project_root": str(project)}, home)


@pytest.mark.parametrize("path", ["../outside.md", "/etc/passwd", "README.md", "AGENTS.txt",
                                  ".claude/skills/Bad_Name/SKILL.md", ".claude/skills/a/other.md"])
def test_only_allowed_paths(project, home, path):
    with pytest.raises(InstructionError):
        handle({"op": "read", "scope": "project", "path": path, "project_root": str(project)}, home)


def test_a_link_out_of_the_root_is_refused(project, home, tmp_path):
    (tmp_path / "secret.md").write_text("secret\n")
    (project / "CLAUDE.md").symlink_to(tmp_path / "secret.md")
    with pytest.raises(InstructionError, match="за пределы"):
        handle({"op": "read", "scope": "project", "path": "CLAUDE.md", "project_root": str(project)}, home)
    listed = handle({"op": "list", "scope": "project", "project_root": str(project)}, home)
    assert "CLAUDE.md" not in [f["path"] for f in listed["files"]]


def test_worker_files_show_who_they_act_on(home):
    files = {f["path"]: f for f in handle({"op": "list", "scope": "worker"}, home)["files"]}
    # The shared CLAUDE.md acts on the profile that links to it, not on the one with its own files.
    assert files["claude/CLAUDE.md"]["accounts"] == ["claude-main"]
    assert files["claude/skills/shared-skill/SKILL.md"]["accounts"] == ["claude-main"]
    assert files["accounts/claude-own/claude/skills/mine/SKILL.md"]["accounts"] == ["claude-own"]
    assert not any("synced" in path for path in files)
    assert "accounts/claude-main/claude/CLAUDE.md" not in files  # a link to the shared file is not repeated


def test_shared_files_are_backed_up_rotated_and_restored(home):
    path = "claude/CLAUDE.md"
    current = "global\n"
    for index in range(KEEP_BACKUPS + 3):
        text = f"v{index}\n"
        handle({"op": "write", "scope": "worker", "path": path, "content": text, "base_sha256": sha(current)}, home)
        current = text
    backups = handle({"op": "backups", "scope": "worker", "path": path}, home)["backups"]
    assert len(backups) == KEEP_BACKUPS and backups[0]["content"] == f"v{KEEP_BACKUPS + 1}\n"
    handle({"op": "restore", "scope": "worker", "path": path, "backup": backups[-1]["id"], "base_sha256": sha(current)}, home)
    assert (home / ".claude" / "CLAUDE.md").read_text() == backups[-1]["content"]


def test_skills_are_created_and_deleted(project, home):
    path = ".claude/skills/panel-check/SKILL.md"
    created = handle({"op": "write", "scope": "project", "path": path, "content": "---\nname: panel-check\n---\n",
                      "base_sha256": None, "project_root": str(project)}, home)
    assert created["commit"]
    handle({"op": "delete", "scope": "project", "path": path, "base_sha256": created["sha256"],
            "project_root": str(project)}, home)
    assert not (project / ".claude" / "skills" / "panel-check").exists()
    with pytest.raises(InstructionError, match="только навыки"):
        handle({"op": "delete", "scope": "project", "path": "AGENTS.md", "base_sha256": None,
                "project_root": str(project)}, home)


def test_too_big_files_are_refused(project, home):
    agents = handle({"op": "read", "scope": "project", "path": "AGENTS.md", "project_root": str(project)}, home)
    with pytest.raises(InstructionError, match="256"):
        handle({"op": "write", "scope": "project", "path": "AGENTS.md", "content": "x" * (256 * 1024 + 1),
                "base_sha256": agents["sha256"], "project_root": str(project)}, home)
