import asyncio
import json
import subprocess
import threading

import pytest

from aihub_agents import repo
from aihub_agents.worker import Worker


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a").write_text("one\n")
    git(tmp_path, "add", "a")
    git(tmp_path, "commit", "-m", "initial")
    git(tmp_path, "checkout", "-b", "aihub/s1/x")
    (tmp_path / "a").write_text("one\ntwo\n")
    git(tmp_path, "commit", "-am", "agent")
    git(tmp_path, "checkout", "main")
    (tmp_path / "b").write_text("main\n")
    git(tmp_path, "add", "b")
    git(tmp_path, "commit", "-m", "main")
    git(tmp_path, "merge", "--no-ff", "aihub/s1/x", "-m", "merge")
    return tmp_path


def test_graph_and_commit(repository):
    result = repo.repo_graph(repository, 2)
    assert result["base"] == "main" and result["has_more"]
    assert len(result["commits"][0]["parents"]) == 2
    assert result["commits"][0]["refs"] == ["main"]
    assert result["commits"][1]["sha"] in result["commits"][0]["parents"]
    branch = next(b for b in result["branches"] if b["name"] == "aihub/s1/x")
    assert (branch["ahead"], branch["behind"], branch["merged"]) == (0, 2, True)
    commit = repo.repo_commit(repository, branch["head"])
    assert commit["files"] == [{"path": "a", "added": 1, "deleted": 0}]


def test_actions(repository):
    with pytest.raises(ValueError):
        repo.repo_action(repository, "reset", "1")
    with pytest.raises(ValueError):
        repo.repo_action(repository, "delete_branch", "main")
    git(repository, "checkout", "-b", "aihub/unmerged")
    (repository / "c").write_text("x")
    git(repository, "add", "c")
    git(repository, "commit", "-m", "unmerged")
    git(repository, "checkout", "main")
    with pytest.raises(ValueError, match="not merged"):
        repo.repo_action(repository, "delete_branch", "aihub/unmerged")
    assert repo.repo_action(repository, "delete_branch", "aihub/s1/x")["ok"]


def test_gh(repository, tmp_path, monkeypatch):
    git(repository, "remote", "add", "origin", "git@github-ai-dev-hub:example/repo.git")
    script = tmp_path / "gh"
    script.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["GH_LOG"], "a") as f: f.write(json.dumps(args) + "\\n")
if args[:2] == ["auth", "status"]:
    sys.exit(int(os.environ.get("AUTH_FAIL", "0")))
if args[:2] == ["api", "user"]:
    print("test-login")
elif args[:2] == ["pr", "list"]:
    print(json.dumps([{"number": 2, "author": {"login": "a"}, "mergeable": "MERGEABLE", "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}, {"status": "IN_PROGRESS"}]}]))
elif args[:2] == ["run", "list"]:
    print(json.dumps([{"databaseId": 1, "status": "completed", "conclusion": "failure", "startedAt": "2024-01-01T00:00:00Z", "updatedAt": "2024-01-01T00:01:00Z"}]))
elif args[:2] == ["run", "view"]:
    print(json.dumps({"jobs": [{"name": "test", "startedAt": "2024-01-01T00:00:00Z", "completedAt": "2024-01-01T00:00:30Z"}]}))
elif args[:2] == ["repo", "view"]:
    if os.environ.get("REPO_FAIL"):
        sys.exit(1)
    if "nameWithOwner,url" in args:
        print(json.dumps({"nameWithOwner": "example/repo", "url": "https://github.com/example/repo"}))
    else:
        print(json.dumps({"mergeCommitAllowed": False, "squashMergeAllowed": True}))
elif args[:2] == ["pr", "close"]:
    print("ghp_secret123 github_pat_secret123", file=sys.stderr); sys.exit(1)
''')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:" + __import__("os").environ["PATH"])
    monkeypatch.setenv("GH_LOG", str(tmp_path / "log"))
    result = repo.repo_github(repository, "worker")
    assert result["available"] and result["login"] == "test-login"
    assert result["pulls"][0]["checks"] == {"state": "failure", "passed": 1, "failed": 1, "pending": 1}
    assert result["runs"][0]["duration_s"] == 60
    assert result["runs"][0]["jobs"][0]["duration_s"] == 30
    repo.repo_action(repository, "merge_pr", "2")
    repo.repo_action(repository, "rerun_failed", "1")
    sha = git(repository, "rev-parse", "HEAD")
    assert repo.repo_commit(repository, sha)["url"] == f"https://github.com/example/repo/commit/{sha}"
    argv = [json.loads(line) for line in (tmp_path / "log").read_text().splitlines()]
    assert ["pr", "merge", "2", "--squash", "--repo", "example/repo"] in argv
    assert all(args[args.index("--repo") + 1] == "example/repo"
               for args in argv if args[:2] in (["pr", "list"], ["pr", "merge"],
                                                ["run", "list"], ["run", "view"], ["run", "rerun"])
               )
    assert ["repo", "view", "example/repo", "--json", "mergeCommitAllowed,squashMergeAllowed"] in argv
    assert all("--admin" not in args for args in argv)
    with pytest.raises(RuntimeError) as exc:
        repo.repo_action(repository, "close_pr", "2")
    assert "secret123" not in str(exc.value)
    close_args = json.loads((tmp_path / "log").read_text().splitlines()[-1])
    assert close_args[-2:] == ["--repo", "example/repo"]
    monkeypatch.setenv("REPO_FAIL", "1")
    assert repo.repo_github(repository, "worker")["reason"] == "No GitHub remote"
    assert repo.repo_commit(repository, sha)["url"] is None
    monkeypatch.delenv("REPO_FAIL")
    monkeypatch.setenv("AUTH_FAIL", "1")
    assert not repo.repo_github(repository, "worker")["available"]


def test_worker_runs_repo_in_background(monkeypatch):
    worker = Worker("http://localhost", "worker", "token")
    started, release = threading.Event(), threading.Event()
    def slow(*args):
        started.set()
        release.wait(5)
        return {"ok": True}
    monkeypatch.setattr("aihub_agents.worker.repo_graph", slow)
    posted = []
    class Response:
        is_success = True
        def json(self):
            return {"id": "1", "kind": "repo_graph", "path": "/tmp", "response": {}}
    async def request(client, method, path, **kwargs):
        if method == "GET":
            return Response()
        posted.append(kwargs["json"])
    monkeypatch.setattr(worker, "_request", request)
    async def run():
        await asyncio.wait_for(worker.service_workspace_request(None), 1)
        assert await asyncio.to_thread(started.wait, 1)
        assert not posted
        release.set()
        await asyncio.gather(*worker._background)
    asyncio.run(run())
    assert posted == [{"result": {"ok": True}}]
