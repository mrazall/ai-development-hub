#!/usr/bin/env python3
"""After `quickstart.sh --demo`: create a session the way the panel does (demo project, a demo account, a mock
engine) and wait until the demo worker completes it. Standard library only.

usage: scripts/demo-smoke.py http://127.0.0.1:58080 .aihub/admin-password
"""
import json
import sys
import time
import urllib.request
import uuid

base, password_file = sys.argv[1].rstrip("/") + "/api/v0", sys.argv[2]


def call(path, data=None, token=None):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    body = json.dumps(data).encode() if data is not None else None
    with urllib.request.urlopen(urllib.request.Request(base + path, body, headers), timeout=30) as response:
        return json.load(response)


password = open(password_file, encoding="utf-8").read().strip()
token = call("/auth/login", {"username": "admin", "password": password})["access_token"]
task = call("/projects/demo/tasks", {"title": "demo smoke", "body": "Write a file", "idempotency_key": str(uuid.uuid4())}, token)
session = call("/sessions", {
    "task_id": task["id"], "project_id": "demo", "worker_id": "demo-worker", "engine": "mock_write",
    "provider": "anthropic", "model": "mock", "auth_mode": "subscription", "workdir": "/work/demo",
    "account_profile_id": "demo-claude", "title": "demo smoke",
}, token)
for _ in range(60):
    status = call(f"/sessions/{session['id']}", token=token)["status"]
    if status in {"completed", "failed"}:
        break
    time.sleep(2)
print("demo session:", status)
sys.exit(0 if status == "completed" else 1)
