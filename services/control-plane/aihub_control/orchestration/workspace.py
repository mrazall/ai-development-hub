from __future__ import annotations

import json
import subprocess
from pathlib import Path

MAX_FILE_SIZE = 1024 * 1024


class InvalidWorkspacePath(ValueError):
    pass


def safe_path(workdir: str, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise InvalidWorkspacePath("path must be relative")
    candidate = Path(relative)
    if relative != "." and any(part in {"", ".", ".."} for part in candidate.parts):
        raise InvalidWorkspacePath("path contains an invalid component")
    root = Path(workdir).resolve()
    resolved = (root / candidate).resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise InvalidWorkspacePath("path escapes workspace")
    return resolved


def read_file(workdir: str, relative: str) -> dict:
    path = safe_path(workdir, relative)
    if not path.is_file():
        raise FileNotFoundError(relative)
    size = path.stat().st_size
    data = path.read_bytes()[:MAX_FILE_SIZE]
    binary = b"\x00" in data
    return {
        "path": relative,
        "size": size,
        "truncated": size > MAX_FILE_SIZE,
        "binary": binary,
        "content": None if binary else data.decode("utf-8", errors="replace"),
    }


def list_directory(workdir: str, relative: str) -> dict:
    directory = safe_path(workdir, relative)
    if not directory.is_dir():
        raise NotADirectoryError(relative)
    entries = []
    for item in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name)):
        if item.is_symlink():
            try:
                safe_path(workdir, str(Path(relative) / item.name))
            except InvalidWorkspacePath:
                continue
        entries.append(
            {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            }
        )
    return {"path": relative, "entries": entries}


def git_operation(workdir: str, kind: str, relative: str | None = None) -> dict:
    root = Path(workdir).resolve()
    if kind == "git_status":
        args = ["status", "--short", "--untracked-files=all"]
    elif kind in {"git_diff", "git_diff_staged"}:
        args = ["diff", "--", str(safe_path(workdir, relative or ".").relative_to(root))]
        if kind == "git_diff_staged":
            args.insert(1, "--cached")
    elif kind == "git_log":
        args = ["log", "-20", "--format=%H%x00%an%x00%aI%x00%s"]
    else:
        raise ValueError("unsupported git operation")
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=8, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip()[:500] or "git operation failed")
    if kind == "git_status":
        files = []
        for line in completed.stdout.splitlines():
            if len(line) >= 3:
                files.append({"path": line[3:], "index": line[0], "worktree": line[1]})
        return {
            "branch": subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip(),
            "ahead": 0,
            "behind": 0,
            "files": files,
        }
    if kind == "git_log":
        return [
            {"hash": p[0], "author": p[1], "time": p[2], "subject": p[3]}
            for line in completed.stdout.splitlines()
            if len(p := line.split("\x00", 3)) == 4
        ]
    return {
        "diff": completed.stdout[:MAX_FILE_SIZE],
        "truncated": len(completed.stdout) > MAX_FILE_SIZE,
    }


def execute_request(workdir: str, kind: str, path: str | None) -> dict:
    if kind == "list":
        return list_directory(workdir, path or ".")
    if kind == "file":
        return read_file(workdir, path or "")
    return git_operation(workdir, kind, path)
