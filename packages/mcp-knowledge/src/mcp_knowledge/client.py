from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx


RETRIES = 5
RETRY_STATUSES = {502, 503, 504}


class KnowledgeClient:
    """Small, synchronous client. ACL is intentionally delegated to knowledge."""

    def __init__(self, base_url: str, principal: str | None = None,
                 transport: httpx.BaseTransport | None = None, *, hub_token: str | None = None,
                 hub_mode: bool = False):
        self.base_url = base_url.rstrip("/")
        self.principal = principal
        self.hub_mode = hub_mode or bool(hub_token)
        self.hub_token = hub_token
        headers = {"Authorization": f"Bearer {hub_token}"} if self.hub_mode and hub_token else {
            "X-AIHub-Principal": principal or ""
        }
        self._sleep = time.sleep
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            transport=transport,
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        # A hub restart answers 502/503/504 or drops the connection for a few seconds; an agent that
        # gets an error here gives up on the whole task, so wait it out (~45 s) before failing.
        for attempt in range(RETRIES + 1):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError:
                if attempt == RETRIES:
                    raise
            else:
                if response.status_code not in RETRY_STATUSES or attempt == RETRIES:
                    break
            self._sleep(min(2**attempt, 15))
        if response.is_error:
            detail = response.reason_phrase
            if response.content:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                candidate = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(candidate, str) and candidate:
                    detail = candidate[:500]
            raise RuntimeError(f"knowledge API {response.status_code}: {detail}")
        payload = response.json()
        return payload

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        path = "/api/v0/knowledge/search" if self.hub_mode else "/search"
        return self._request("GET", path, params={"q" if self.hub_mode else "query": query, "limit": limit})

    def read(self, document_id: str) -> dict[str, Any]:
        prefix = "/api/v0/knowledge/documents/" if self.hub_mode else "/documents/"
        return self._request("GET", f"{prefix}{quote(document_id, safe='')}")

    def index_status(self) -> dict[str, Any]:
        return self._request("GET", "/index/status")

    def write_draft(self, project_id: str, title: str, content: str, kind: str = "draft") -> dict[str, Any]:
        if self.hub_mode:
            return self._request("POST", "/api/v0/knowledge/drafts", json={"project_id": project_id, "title": title, "content": content, "kind": kind})
        return self._request(
            "POST", "/drafts", json={"project_id": project_id, "title": title, "content": content, "kind": kind}
        )

    def draft(self, title: str, content: str, project_id: str | None = None) -> dict[str, Any]:
        """Create a draft through the hub (the hub infers the personal project)."""
        if self.hub_mode and project_id is None:
            return self._request("POST", "/api/v0/knowledge/drafts", json={"title": title, "content": content})
        if project_id is None:
            raise ValueError("project_id is required in direct mode")
        return self.write_draft(project_id, title, content)

    def handoff_create(self, project_id: str, title: str, content: str) -> dict[str, Any]:
        return self.write_draft(project_id, title, content, kind="handoff")

    def decisions(self, query: str = "decision", limit: int = 10) -> dict[str, Any]:
        return self.search(query, limit)

    def context(self, query: str, limit: int = 5) -> dict[str, Any]:
        result = self.search(query, limit)
        result["documents"] = [self.read(hit["doc_id"]) for hit in result.get("hits", [])]
        return result

    def handoff_get(self, document_id: str) -> dict[str, Any]:
        return self.read(document_id)

    def propose_update(self, project_id: str, title: str, content: str) -> dict[str, Any]:
        return self.write_draft(project_id, title, content, kind="proposal")

    # Orchestration endpoints are enabled by the hub only for a scoped token.
    def orch_spawn_executor(self, orchestrator_id: str, title: str, prompt: str,
                            reuse_branch_of: str | None = None) -> dict[str, Any]:
        payload = {"title": title, "prompt": prompt}
        if reuse_branch_of:
            payload["reuse_branch_of"] = reuse_branch_of
        return self._request("POST", f"/api/v0/orchestrations/{quote(orchestrator_id, safe='')}/executors", json=payload)

    def orch_list_executors(self, orchestrator_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/api/v0/orchestrations/{quote(orchestrator_id, safe='')}/executors")
        return result if isinstance(result, list) else result.get("executors", [])

    def orch_get_executor(self, orchestrator_id: str, executor_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v0/orchestrations/{quote(orchestrator_id, safe='')}/executors/{quote(executor_id, safe='')}")

    def orch_set_plan(self, orchestrator_id: str, steps: list[dict]) -> dict[str, Any]:
        return self._request("POST", f"/api/v0/orchestrations/{quote(orchestrator_id, safe='')}/plan", json={"steps": steps})

    def orch_request_merge(self, orchestrator_id: str, executor_id: str, summary: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v0/orchestrations/{quote(orchestrator_id, safe='')}/executors/{quote(executor_id, safe='')}/merge-request",
            json={"summary": summary},
        )

    def orch_stop_executor(self, orchestrator_id: str, executor_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v0/orchestrations/{quote(orchestrator_id, safe='')}/executors/{quote(executor_id, safe='')}/stop")
