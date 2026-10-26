from pathlib import Path

from fastapi.testclient import TestClient

from aihub_knowledge import api
from aihub_knowledge.acl import Principal, sign_principal


def test_draft_requires_project_access(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api.settings, "internal_secret", "test-secret")
    monkeypatch.setattr(api.settings, "vault_dir", tmp_path)
    header = sign_principal(Principal("u", "viewer", frozenset({"other"})), "test-secret")
    response = TestClient(api.app).post(
        "/drafts",
        headers={"X-AIHub-Principal": header},
        json={"project_id": "alpha", "title": "Draft", "content": "body"},
    )
    assert response.status_code == 403
    assert not list(tmp_path.rglob("*.md"))


def test_draft_writes_only_project_handoff(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api.settings, "internal_secret", "test-secret")
    monkeypatch.setattr(api.settings, "vault_dir", tmp_path)
    header = sign_principal(Principal("u", "viewer", frozenset({"alpha"})), "test-secret")
    response = TestClient(api.app).post(
        "/drafts",
        headers={"X-AIHub-Principal": header},
        json={"project_id": "alpha", "title": "A useful draft", "content": "body"},
    )
    assert response.status_code == 201
    written = list((tmp_path / "_Агенты" / "alpha").glob("*-A-useful-draft.md"))
    assert len(written) == 1
    assert "body" in written[0].read_text(encoding="utf-8")
    assert "status: new" in written[0].read_text(encoding="utf-8")


def test_draft_reports_read_only_vault(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api.settings, "internal_secret", "test-secret")
    monkeypatch.setattr(api.settings, "vault_dir", tmp_path / "missing")
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("ro")))
    header = sign_principal(Principal("u", "admin", frozenset()), "test-secret")
    response = TestClient(api.app).post(
        "/drafts",
        headers={"X-AIHub-Principal": header},
        json={"project_id": "alpha", "title": "Draft", "content": "body"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "vault is read-only"


def test_drafts_list_read_and_dismiss(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api.settings, "internal_secret", "test-secret")
    monkeypatch.setattr(api.settings, "vault_dir", tmp_path)
    client = TestClient(api.app)
    alpha = {"X-AIHub-Principal": sign_principal(Principal("u", "viewer", frozenset({"alpha"})), "test-secret")}
    other = {"X-AIHub-Principal": sign_principal(Principal("v", "viewer", frozenset({"beta"})), "test-secret")}
    created = client.post("/drafts", headers=alpha, json={"project_id": "alpha", "title": "Сеть и доступы", "content": "новый порт"})
    assert created.status_code == 201
    draft_id = created.json()["id"]
    assert "Сеть-и-доступы" in draft_id
    listed = client.get("/drafts", headers=alpha).json()
    assert [item["id"] for item in listed] == [draft_id]
    assert listed[0]["status"] == "new" and listed[0]["title"] == "Сеть и доступы"
    assert client.get("/drafts", headers=other).json() == []
    assert client.get(f"/drafts/{draft_id}", headers=other).status_code == 403
    assert client.get(f"/drafts/{draft_id}", headers=alpha).json()["content"] == "новый порт"
    dismissed = client.post(f"/drafts/{draft_id}/status", headers=alpha, json={"status": "dismissed"})
    assert dismissed.json()["status"] == "dismissed"
    assert client.get(f"/drafts/{draft_id}", headers=alpha).json()["content"] == "новый порт"


def test_draft_path_cannot_escape(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api.settings, "internal_secret", "test-secret")
    monkeypatch.setattr(api.settings, "vault_dir", tmp_path)
    admin = {"X-AIHub-Principal": sign_principal(Principal("u", "admin", frozenset()), "test-secret")}
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    response = TestClient(api.app).get("/drafts/alpha/..%2F..%2Fsecret.md", headers=admin)
    assert response.status_code in {400, 404}
