from pathlib import Path

from aihub_knowledge.embeddings import FakeEmbeddingBackend
from aihub_knowledge.reconcile import InMemoryIndex


def test_reconcile_create_modify_delete_and_acl(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    base = """---\nid: {id}\nproject_id: {project}\ntype: overview\ntitle: {id}\nupdated_at: 2026-10-23T00:00:00Z\nsource: human\nstatus: active\nvisibility: {visibility}\nschema_version: 1\n---\n# Notes\n{body}\n"""
    (root / "a.md").write_text(base.format(id="a", project="alpha", visibility="private", body="needle"))
    (root / "b.md").write_text(base.format(id="b", project="beta", visibility="private", body="needle"))
    index = InMemoryIndex()
    index.reconcile(root, FakeEmbeddingBackend())
    assert len(index.search("needle", {"alpha"})) == 1
    assert len(index.search("needle", {"other"})) == 0
    (root / "a.md").unlink()
    index.reconcile(root, FakeEmbeddingBackend())
    assert not index.search("needle", {"alpha"})
