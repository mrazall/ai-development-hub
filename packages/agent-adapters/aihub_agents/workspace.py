from __future__ import annotations

import shutil
import re
import subprocess
from pathlib import Path

MAX_FILE_SIZE = 1024 * 1024


def build_worktree_command(base_workdir: str, workdir: str, branch: str, base_branch: str = "main") -> list[str]:
    """Build the deterministic git command used for a fresh executor worktree."""
    return ["git", "-C", base_workdir, "worktree", "add", workdir, "-b", branch, base_branch]


def build_reuse_worktree_command(workdir: str, branch: str) -> list[str]:
    return ["git", "-C", workdir, "worktree", "add", workdir, branch]


def prepare_worktree(base_workdir: str, workdir: str, branch: str, base_branch: str = "main") -> None:
    root = Path(base_workdir).expanduser().resolve()
    target = Path(workdir).expanduser().resolve()
    if not branch:
        raise ValueError("executor has no branch")
    if root == target or (target / ".git").exists():
        return  # already a worktree (e.g. a rework run reusing the branch)
    if target.exists():
        # Only service files (attachments) may pre-exist; anything else is someone's data — refuse.
        if any(child.name != ".aihub" for child in target.iterdir()):
            raise RuntimeError(f"{target} exists and is not a git worktree")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(build_worktree_command(str(root), str(target), branch, base_branch), check=True, timeout=30)
    exclude = root / ".git" / "info" / "exclude"
    if exclude.is_file():
        text = exclude.read_text(encoding="utf-8")
        if ".aihub/" not in text:
            exclude.write_text(text.rstrip() + "\n.aihub/\n", encoding="utf-8")


def commit_worktree(workdir: str, message: str) -> str | None:
    """Commit an executor's changes on its branch: Codex cannot write .git from its sandbox.

    Returns the new commit hash, or None when there was nothing to commit.
    """
    run = lambda *args: subprocess.run(["git", "-C", workdir, *args], capture_output=True, text=True, timeout=120)  # noqa: E731
    if not run("status", "--porcelain").stdout.strip():
        return None
    run("add", "-A")
    result = run("commit", "-m", message)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or "git commit failed")
    return run("rev-parse", "--short", "HEAD").stdout.strip()


def merge_branch(workdir: str, branch: str, base_branch: str) -> dict:
    """Merge an executor branch into the base branch of the orchestration checkout (owner-approved merge).

    Refuses when the checkout is not on the base branch or has uncommitted changes; a conflicting merge
    is aborted, so the checkout is left as it was.
    """
    run = lambda *args: subprocess.run(["git", "-C", workdir, *args], capture_output=True, text=True, timeout=120)  # noqa: E731
    if not re.fullmatch(r"[\w./-]+", branch or "") or not re.fullmatch(r"[\w./-]+", base_branch or ""):
        raise ValueError("invalid branch name")
    current = run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if current != base_branch:
        raise RuntimeError(f"checkout is on {current or '?'}, not {base_branch}")
    if run("status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise RuntimeError("base checkout has uncommitted changes")
    result = run("merge", "--no-ff", "--no-edit", branch)
    if result.returncode != 0:
        run("merge", "--abort")
        raise RuntimeError("merge conflict: " + ((result.stdout or "") + (result.stderr or "")).strip()[-400:])
    return {"merged": branch, "into": base_branch, "head": run("rev-parse", "--short", "HEAD").stdout.strip()}


def _path(workdir: str | Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise ValueError("path must be relative")
    if relative != "." and any(part in {"", ".", ".."} for part in Path(relative).parts):
        raise ValueError("path escapes workspace")
    root = Path(workdir).resolve()
    result = (root / relative).resolve()
    if result != root and root not in result.parents:
        raise ValueError("path escapes workspace")
    return result


def safe_path(workdir: str | Path, relative: str) -> Path:
    """Resolve a relative worker path and reject traversal/symlink escapes."""
    return _path(workdir, relative)


def make_project_dir(path: str, allowed_roots: list[str]) -> dict:
    """Create a project folder, but only inside the worker's allowed roots."""
    if not path or "\x00" in path:
        raise ValueError("path is required")
    target = Path(path).expanduser().resolve(strict=False)
    roots = [Path(root).expanduser().resolve(strict=False) for root in allowed_roots]
    # The root itself is never a project folder; only paths strictly below it.
    if not any(root in target.parents for root in roots):
        raise ValueError("path is outside worker allowed roots")
    existed = target.is_dir()
    target.mkdir(parents=True, exist_ok=True)
    return {"created": not existed, "path": str(target)}


def execute_request(workdir: str, kind: str, path: str | None) -> dict:
    root = Path(workdir).resolve()
    if kind == "list":
        directory = _path(workdir, path or ".")
        return {
            "path": path or ".",
            "entries": [
                {
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
                for item in sorted(directory.iterdir())
                if not item.is_symlink() or root in item.resolve().parents
            ],
        }
    if kind == "file":
        file = _path(workdir, path or "")
        size = file.stat().st_size
        data = file.read_bytes()[:MAX_FILE_SIZE]
        binary = b"\x00" in data
        return {
            "path": path,
            "size": size,
            "truncated": size > MAX_FILE_SIZE,
            "binary": binary,
            "content": None if binary else data.decode("utf-8", errors="replace"),
        }
    if kind == "git_status":
        args = ["status", "--short", "--untracked-files=all"]
    elif kind in {"git_diff", "git_diff_staged"}:
        args = ["diff", "--", str(_path(workdir, path or ".").relative_to(root))]
        if kind == "git_diff_staged":
            args.insert(1, "--cached")
    elif kind == "git_log":
        args = ["log", "-20", "--format=%H%x00%an%x00%aI%x00%s"]
    else:
        raise ValueError("unsupported operation")
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=8, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:500] or "git operation failed")
    if kind == "git_status":
        return {
            "branch": subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip(),
            "ahead": 0,
            "behind": 0,
            "files": [
                {"path": line[3:], "index": line[0], "worktree": line[1]}
                for line in result.stdout.splitlines()
                if len(line) >= 3
            ],
        }
    if kind == "git_log":
        return [
            {"hash": p[0], "author": p[1], "time": p[2], "subject": p[3]}
            for line in result.stdout.splitlines()
            if len(p := line.split("\x00", 3)) == 4
        ]
    return {"diff": result.stdout[:MAX_FILE_SIZE], "truncated": len(result.stdout) > MAX_FILE_SIZE}


__all__ = ["execute_request"]
