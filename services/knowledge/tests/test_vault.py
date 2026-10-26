from pathlib import Path

from aihub_knowledge.chunking import chunk_document
from aihub_knowledge.vault import parse_markdown, scan_vault


def write_doc(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


FRONT = """---\nid: doc-1\nproject_id: alpha\ntype: overview\ntitle: Test\nupdated_at: 2026-10-23T00:00:00Z\nsource: human\nstatus: active\nvisibility: private\nschema_version: 1\n---\n"""


def test_parser_and_exclusions(tmp_path: Path):
    root = tmp_path / "vault"
    write_doc(root, "ok.md", FRONT + "# Intro\nРусский текст")
    write_doc(root, ".env.md", FRONT + "bad")
    write_doc(root, "secret.md", FRONT + "token: sk-abcdefghijklmnop")
    write_doc(root, "bad.md", "# no metadata")
    docs, errors = scan_vault(root)
    assert [doc.id for doc in docs] == ["vault:bad.md", "doc-1"]
    assert len(errors) == 1


def test_chunk_ids_are_stable_for_other_section_edit(tmp_path: Path):
    root = tmp_path / "vault"
    path = write_doc(root, "ok.md", FRONT + "# A\nalpha\n# B\nbeta")
    first = parse_markdown(path, root).document
    assert first
    old = {chunk.heading: chunk.id for chunk in chunk_document(first)}
    path.write_text(FRONT + "# A\nalpha\n# B\nbeta changed", encoding="utf-8")
    second = parse_markdown(path, root).document
    assert second
    new = {chunk.heading: chunk.id for chunk in chunk_document(second)}
    assert new["A"] == old["A"]


def test_plain_note_gets_stable_derived_metadata(tmp_path: Path):
    root = tmp_path / "vault"
    path = write_doc(root, "nested/🏠 homelab.md", "# 🏠 Домашняя сеть\nТекст заметки")
    parsed = parse_markdown(path, root)

    assert parsed.document
    assert parsed.document.id == "vault:nested/🏠 homelab.md"
    assert parsed.document.title == "Домашняя сеть"
    assert parsed.document.type == "note"
    assert parsed.document.source == "vault"
    assert parsed.document.status == "active"
    assert parsed.document.visibility == "private"
    assert parsed.document.project_id is None
    assert parsed.document.updated_at.tzinfo is not None


def test_partial_frontmatter_is_completed_from_note(tmp_path: Path):
    root = tmp_path / "vault"
    path = write_doc(root, "partial.md", "---\ntitle: Custom title\n---\n# Ignored heading\nbody")
    parsed = parse_markdown(path, root)

    assert parsed.document
    assert parsed.document.id == "vault:partial.md"
    assert parsed.document.title == "Custom title"
    assert parsed.document.type == "note"
    assert parsed.document.content == "# Ignored heading\nbody"


def test_new_secret_formats_are_not_indexed(tmp_path: Path):
    root = tmp_path / "vault"
    secrets = (
        "vless://user@example.com?security=tls",
        "vmess://eyJ2IjoiMiIsInBzIjoic2VjcmV0In0=",
        "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.com:443",
        "trojan://password@example.com:443",
        "tskey-abcdefghijklmnop",
        "Authorization: Bearer abcdefghijklmnopqrst",
    )
    for number, secret in enumerate(secrets):
        write_doc(root, f"secret-{number}.md", f"# Note\n{secret}")

    documents, errors = scan_vault(root)

    assert documents == []
    assert len(errors) == len(secrets)
    assert all(error.reason == "secret detected; document was not indexed" for error in errors)


def test_obsidian_and_trash_directories_are_skipped(tmp_path: Path):
    root = tmp_path / "vault"
    write_doc(root, ".obsidian/config.md", "# secret-looking but ignored")
    write_doc(root, ".trash/deleted.md", "# deleted")

    documents, errors = scan_vault(root)

    assert documents == []
    assert errors == []
