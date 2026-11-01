from __future__ import annotations

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

_TOKEN = re.compile(r"gh[pousr]_\w+|github_pat_\w+")


def clean_error(value: object) -> str:
    message = _TOKEN.sub("[REDACTED]", str(value))
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(name)
        if token:
            message = message.replace(token, "[REDACTED]")
    return message[:500]


def _run(path, *args, check=True):
    try:
        result = subprocess.run(args, cwd=path, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(clean_error(exc)) from None
    if check and result.returncode:
        raise RuntimeError(clean_error(result.stderr.strip() or "Command failed"))
    return result


def _git(path, *args, check=True):
    return _run(path, "git", *args, check=check)


def _gh(path, *args):
    result = _run(path, "gh", *args)
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("Invalid response from gh") from None


def _base(path):
    ref = _git(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)
    if ref.returncode == 0 and ref.stdout.strip().startswith("origin/"):
        return ref.stdout.strip()[7:]
    for name in ("main", "master"):
        if _git(path, "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode == 0:
            return name
    raise RuntimeError("Default branch not found")


def _base_ref(path, base):
    if _git(path, "show-ref", "--verify", "--quiet", f"refs/heads/{base}", check=False).returncode == 0:
        return f"refs/heads/{base}"
    return f"refs/remotes/origin/{base}"


def repo_graph(path, limit=200):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Invalid commit limit")
    base = _base(path)
    base_ref = _base_ref(path, base)
    output = _git(path, "for-each-ref", "--format=%(refname)%00%(objectname)", "refs/heads", "refs/remotes/origin").stdout
    branches = []
    for line in output.splitlines():
        ref, head = line.split("\0", 1)
        remote = ref.startswith("refs/remotes/")
        name = ref.removeprefix("refs/remotes/") if remote else ref.removeprefix("refs/heads/")
        if name == "origin/HEAD":
            continue
        counts = _git(path, "rev-list", "--left-right", "--count", f"{base_ref}...{ref}").stdout.split()
        merged = _git(path, "merge-base", "--is-ancestor", ref, base_ref, check=False)
        if merged.returncode not in (0, 1):
            raise RuntimeError(clean_error(merged.stderr))
        branches.append({"name": name, "head": head, "is_remote": remote, "ahead": int(counts[1]),
                             "behind": int(counts[0]), "merged": merged.returncode == 0})
    branches.sort(key=lambda b: (0 if b["name"] == base and not b["is_remote"] else 1 if not b["is_remote"] else 2, b["name"]))
    log = _git(path, "log", "--all", "--topo-order", f"-n{limit + 1}",
               "--format=%H%x00%P%x00%s%x00%an%x00%aI%x00%D%x00").stdout
    commits = []
    for line in log.splitlines():
        fields = line.split("\0")
        if len(fields) < 6:
            continue
        sha, parents, subject, author, at, decorations = fields[:6]
        refs = []
        for ref in decorations.split(", ") if decorations else []:
            if ref.startswith("HEAD -> "):
                ref = ref[8:]
            elif ref == "HEAD" or ref.startswith("origin/HEAD -> "):
                continue
            refs.append(ref)
        commits.append({"sha": sha, "parents": parents.split(), "subject": subject, "author": author, "at": at, "refs": refs})
    return {"base": base, "branches": branches, "commits": commits[:limit], "has_more": len(commits) > limit}


def repo_commit(path, sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        raise ValueError("Invalid commit SHA")
    output = _git(path, "show", "--numstat", "--format=", "--no-renames", sha, "--").stdout
    files = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            added, deleted, name = parts
            files.append({"path": name, "added": int(added) if added.isdigit() else None,
                              "deleted": int(deleted) if deleted.isdigit() else None})
    try:
        info = _repo_info(path)
        url = f"{info['url'].rstrip('/')}/commit/{sha}"
    except (RuntimeError, KeyError, TypeError, AttributeError):
        url = None
    return {"sha": sha, "files": files, "url": url}


def _duration(start, end):
    if not start or not end:
        return None
    try:
        return max(0, int((datetime.fromisoformat(end) -
                           datetime.fromisoformat(start)).total_seconds()))
    except (ValueError, TypeError):
        return None


def _checks(items):
    passed = failed = pending = 0
    for item in items or []:
        status = (item.get("conclusion") or item.get("state") or "").upper()
        if status in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            passed += 1
        elif status in {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STALE"}:
            failed += 1
        else:
            pending += 1
    return {"state": "failure" if failed else "pending" if pending else "success" if passed else "none",
                "passed": passed, "failed": failed, "pending": pending}


def _repo_info(path):
    info = _gh(path, "repo", "view", "--json", "nameWithOwner,url")
    if not isinstance(info, dict) or not info.get("nameWithOwner") or not info.get("url"):
        raise RuntimeError("No GitHub remote")
    return info


def repo_github(path, worker_name):
    empty = {"available": False, "reason": None, "login": None, "pulls": [], "runs": []}
    try:
        auth = _run(path, "gh", "auth", "status", check=False)
    except RuntimeError:
        return {**empty, "reason": "gh is not installed"}
    if auth.returncode:
        return {**empty, "reason": f"gh is not logged in on worker {clean_error(worker_name)} — run: gh auth login"}
    try:
        name = _repo_info(path)["nameWithOwner"]
    except RuntimeError:
        return {**empty, "reason": "No GitHub remote"}
    def user_login():
        try:
            result = _run(path, "gh", "api", "user", "--jq", ".login", check=False)
        except RuntimeError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    # Every gh call is a ~1-2 s round trip to GitHub: independent ones go in parallel, not one after another.
    with ThreadPoolExecutor(max_workers=10) as pool:
        login_future = pool.submit(user_login)
        pulls_future = pool.submit(_gh, path, "pr", "list", "--repo", name, "--state", "open", "--json", "number,title,author,headRefName,baseRefName,isDraft,mergeable,reviewDecision,statusCheckRollup,url,updatedAt")
        runs_raw = _gh(path, "run", "list", "--repo", name, "-L", "20", "--json", "databaseId,workflowName,headBranch,event,status,conclusion,startedAt,updatedAt,url")
        runs_raw.sort(key=lambda r: (r.get("startedAt") or "", r.get("databaseId") or 0), reverse=True)
        job_futures = [pool.submit(_gh, path, "run", "view", str(r["databaseId"]), "--repo", name, "--json", "jobs")
                       for r in runs_raw[:10]]
        login, pulls_raw = login_future.result(), pulls_future.result()
        job_lists = [future.result().get("jobs", []) for future in job_futures]
    pulls = []
    for p in pulls_raw:
        pulls.append({"number": p.get("number"), "title": p.get("title"), "author": (p.get("author") or {}).get("login"),
                          "branch": p.get("headRefName"), "base": p.get("baseRefName"), "draft": p.get("isDraft"),
                          "mergeable": {"MERGEABLE": True, "CONFLICTING": False}.get(p.get("mergeable")),
                          "review": {"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "REVIEW_REQUIRED": "review_required"}.get(p.get("reviewDecision")),
                          "checks": _checks(p.get("statusCheckRollup")), "url": p.get("url"), "updated_at": p.get("updatedAt")})
    pulls.sort(key=lambda p: p["number"] or 0, reverse=True)
    runs = []
    for index, r in enumerate(runs_raw):
        jobs = []
        if index < len(job_lists):
            for job in job_lists[index]:
                jobs.append({"name": job.get("name"), "conclusion": job.get("conclusion") or None,
                                 "duration_s": _duration(job.get("startedAt"), job.get("completedAt")), "url": job.get("url")})
        status = r.get("status")
        runs.append({"id": r.get("databaseId"), "workflow": r.get("workflowName"), "branch": r.get("headBranch"),
                         "event": r.get("event"), "status": status if status in {"queued", "in_progress", "completed"} else None,
                         "conclusion": r.get("conclusion") if r.get("conclusion") in {"success", "failure", "cancelled", "skipped"} else None,
                         "started_at": r.get("startedAt"), "duration_s": _duration(r.get("startedAt"), r.get("updatedAt")) if status == "completed" else None,
                         "url": r.get("url"), "jobs": jobs})
    return {"available": True, "reason": None, "login": login or None, "pulls": pulls, "runs": runs}


def repo_action(path, action, target):
    if action not in {"rerun_failed", "merge_pr", "close_pr", "delete_branch"}:
        raise ValueError("Unknown repository action")
    target = str(target)
    if action != "delete_branch":
        if not re.fullmatch(r"[0-9]+", target) or int(target) < 1:
            raise ValueError("Invalid target number")
        name = _repo_info(path)["nameWithOwner"]
        if action == "merge_pr":
            settings = _gh(path, "repo", "view", name, "--json", "mergeCommitAllowed,squashMergeAllowed")
            method = "--merge" if settings.get("mergeCommitAllowed") else "--squash" if settings.get("squashMergeAllowed") else None
            if not method:
                raise RuntimeError("No permitted merge method")
            _run(path, "gh", "pr", "merge", target, method, "--repo", name)
        elif action == "close_pr":
            _run(path, "gh", "pr", "close", target, "--repo", name)
        else:
            _run(path, "gh", "run", "rerun", target, "--failed", "--repo", name)
    else:
        if not target.startswith("aihub/") or _git(path, "check-ref-format", "--branch", target, check=False).returncode:
            raise ValueError("Invalid agent branch")
        base_ref = _base_ref(path, _base(path))
        local = f"refs/heads/{target}"
        remote = f"refs/remotes/origin/{target}"
        existing = [ref for ref in (local, remote) if _git(path, "show-ref", "--verify", "--quiet", ref, check=False).returncode == 0]
        if not existing:
            raise ValueError("Branch not found")
        for ref in existing:
            if _git(path, "merge-base", "--is-ancestor", ref, base_ref, check=False).returncode != 0:
                raise ValueError("Branch is not merged into the default branch")
        if local in existing:
            _git(path, "branch", "-d", target)
        if remote in existing:
            _git(path, "push", "origin", "--delete", target)
    return {"ok": True, "message": f"{action}: {target}"}
