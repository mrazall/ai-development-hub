"""Cached repository views and asynchronous worker requests."""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictBool
from sqlalchemy import select

from ..auth import current_user, db_dep, write_user
from ..deps import project_or_404
from ..models import Project, RepoCache, Session, Worker, WorkerRequest, now
from ..orchestration.notifications import notify_project_users

router = APIRouter()
MISSING = "Repository not found on the project's workers"
TOKEN = re.compile(r"gh[pousr]_\w+|github_pat_\w+", re.IGNORECASE)


def clean(value):
    if isinstance(value, str):
        return TOKEN.sub("[redacted]", value)
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not re.search(r"token|password|secret|^env$", k, re.IGNORECASE)}
    return value


def worker_for(db, project):
    if not project.allowed_paths:
        return None
    workers = {w.id: w for w in db.scalars(select(Worker).where(Worker.status == "online").order_by(Worker.id))}
    last = db.scalars(select(Session).where(Session.project_id == project.id).order_by(Session.created_at.desc()).limit(1)).first()
    if last and last.worker_id in workers:
        return workers[last.worker_id]
    graph = db.get(RepoCache, (project.id, "graph"))
    if graph and graph.fetched_at and not graph.error and graph.worker_id in workers:
        return workers[graph.worker_id]
    return next(iter(workers.values()), None)


def cached(db, project, kind, params):
    # Serialize cache creation and request scheduling even when the row does not exist yet.
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).first()
    cache = db.get(RepoCache, (project.id, kind))
    worker = worker_for(db, project)
    if cache is None:
        cache = RepoCache(project_id=project.id, kind=kind, payload={})
        db.add(cache)
    current = now()
    refreshing = False
    stale = not cache.fetched_at or current - cache.fetched_at > timedelta(seconds=30 if kind == "github" else 60)
    if worker and stale:
        pending = db.scalars(select(WorkerRequest).where(
            WorkerRequest.kind == ("repo_commit" if kind.startswith("commit:") else "repo_" + kind),
            WorkerRequest.status.in_(["queued", "running"]),
            WorkerRequest.created_at >= current - timedelta(seconds=120),
        )).all()
        refreshing = any((r.response or {}).get("project_id") == project.id and
                         (not kind.startswith("commit:") or (r.response or {}).get("sha") == params.get("sha"))
                         for r in pending)
        if not refreshing:
            db.add(WorkerRequest(worker_id=worker.id, kind="repo_commit" if kind.startswith("commit:") else "repo_" + kind,
                                 path=project.allowed_paths[0], response={"project_id": project.id, **params}))
            cache.requested_at = current
            refreshing = True
    db.commit()
    return cache, worker, refreshing


@router.get("/projects/{project_id}/repo/graph")
def graph(project_id: str, limit: int = Query(200, ge=1, le=1000), user=Depends(current_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    cache, worker, refreshing = cached(db, project, "graph", {"limit": limit})
    data = cache.payload or {}
    sessions = db.scalars(select(Session).where(Session.project_id == project_id, Session.branch.is_not(None)).order_by(Session.created_at.desc())).all()
    by_branch = {}
    for session in sessions:
        by_branch.setdefault(session.branch, session)
    branches = []
    for branch in data.get("branches", []):
        branch = dict(branch)
        session = by_branch.get(branch.get("name", "").removeprefix("origin/"))
        branch.update(agent_session_id=session.id if session else None, agent_session_title=session.title if session else None)
        branches.append(branch)
    unavailable = not worker or bool(cache.error and "not a git repository" in cache.error.lower())
    return {"fetched_at": cache.fetched_at, "refreshing": refreshing, "worker_id": cache.worker_id,
            "available": not unavailable, "reason": MISSING if unavailable else cache.error,
            "base": data.get("base"), "has_more": data.get("has_more", False), "branches": branches,
            "commits": data.get("commits", [])[:limit]}


@router.get("/projects/{project_id}/repo/github")
def github(project_id: str, user=Depends(current_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    cache, worker, refreshing = cached(db, project, "github", {})
    data = cache.payload or {}
    unavailable = not worker or bool(cache.error and "not a git repository" in cache.error.lower())
    return {"fetched_at": cache.fetched_at, "refreshing": refreshing, "worker_id": cache.worker_id,
            "available": False if unavailable else data.get("available", False),
            "reason": MISSING if unavailable else (cache.error or data.get("reason")),
            "pulls": data.get("pulls", []), "runs": data.get("runs", [])}


@router.get("/projects/{project_id}/repo/commits/{sha}")
def commit(project_id: str, sha: str, user=Depends(current_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        raise HTTPException(422, "Invalid commit SHA")
    cache, _, refreshing = cached(db, project, "commit:" + sha, {"sha": sha})
    return {"fetched_at": cache.fetched_at, "refreshing": refreshing, "sha": sha,
            "files": (cache.payload or {}).get("files"), "url": (cache.payload or {}).get("url")}


class Action(BaseModel):
    action: str
    target: str
    confirm: StrictBool


@router.post("/projects/{project_id}/repo/actions", status_code=202)
def action(project_id: str, data: Action, user=Depends(write_user), db=Depends(db_dep)):
    project = project_or_404(db, user, project_id)
    if not data.confirm or data.action not in {"rerun_failed", "merge_pr", "close_pr", "delete_branch"}:
        raise HTTPException(422, "Invalid action or confirmation")
    if (data.action == "delete_branch" and not data.target.startswith("aihub/")) or (
        data.action != "delete_branch" and not re.fullmatch(r"[0-9]+", data.target)
    ):
        raise HTTPException(422, "Invalid target")
    worker = worker_for(db, project)
    if not worker:
        raise HTTPException(409, MISSING)
    request = WorkerRequest(worker_id=worker.id, kind="repo_action", path=project.allowed_paths[0],
                            response={"project_id": project.id, "action": data.action, "target": data.target})
    db.add(request)
    db.commit()
    return {"request_id": request.id}


def _ready(pr):
    return not pr.get("draft") and pr.get("mergeable") is True and (pr.get("checks") or {}).get("state") == "success"


def _runs(data, base):
    result = {}
    for run in data.get("runs", []):
        if run.get("branch") == base and run.get("status") == "completed":
            result.setdefault(run.get("workflow"), run.get("conclusion"))
    return result


def finish_repo_request(db, request, payload):
    params = request.response or {}
    project_id = params.get("project_id")
    if not project_id:
        return
    project = db.get(Project, project_id)
    if not project:
        return
    payload = clean(payload)
    if request.kind == "repo_action":
        error = payload.get("error")
        labels = {"merge_pr": "Merged PR", "close_pr": "Closed PR", "rerun_failed": "Reran CI", "delete_branch": "Deleted branch"}
        title = ("Repository action failed" if error else
                 f"{labels.get(params.get('action'), 'Repository action')} {'#' if params.get('action') in {'merge_pr', 'close_pr'} else ''}{params.get('target', '')}")
        notify_project_users(db, project, "repo.action", clean(title), body=error or clean((payload.get("result") or {}).get("message", "")), severity="error" if error else "info")
        return
    kind = "commit:" + params.get("sha", "") if request.kind == "repo_commit" else request.kind.removeprefix("repo_")
    cache = db.get(RepoCache, (project_id, kind))
    if cache is None:
        cache = RepoCache(project_id=project_id, kind=kind, payload={})
        db.add(cache)
    old = cache.payload or {}
    result = payload.get("result") or {}
    if kind == "github" and not payload.get("error") and cache.fetched_at:
        graph_cache = db.get(RepoCache, (project_id, "graph"))
        base = (graph_cache.payload or {}).get("base") if graph_cache else None
        previous = _runs(old, base)
        for workflow, conclusion in _runs(result, base).items():
            before = previous.get(workflow)
            if (before, conclusion) in {("success", "failure"), ("failure", "success")}:
                title = f"CI failed on {base}: {workflow}" if conclusion == "failure" else f"CI fixed on {base}"
                notify_project_users(db, project, "repo.ci", title)
        previous_pr = {p.get("number"): p for p in old.get("pulls", [])}
        for pr in result.get("pulls", []):
            if _ready(pr) and not _ready(previous_pr.get(pr.get("number"), {})):
                notify_project_users(db, project, "repo.pr", f"PR #{pr.get('number')} ready to merge")
    cache.worker_id = request.worker_id
    cache.error = payload.get("error")
    if not cache.error:
        cache.payload = result
    cache.fetched_at = now()
