from types import SimpleNamespace

from aihub_knowledge.graph import ExtractedLink, extract_links, ghost_id, resolve_link


def test_extracts_wikilinks_sections_aliases_embeds_and_relative_markdown():
    links = extract_links(
        "[[Сервисы]] [[Заметка#Раздел|текст]] ![[image.png]] "
        "[ссылка](../notes/Readme.md#intro) [внешняя](https://example.com/x)"
    )
    assert [(link.target, link.embedded, link.relative) for link in links] == [
        ("Сервисы", False, False),
        ("Заметка", False, False),
        ("image.png", True, False),
        ("../notes/Readme.md", False, True),
    ]


def test_resolves_relative_path_before_case_insensitive_stem_and_title():
    docs = [
        SimpleNamespace(id="title", path="other.md", title="VPN и маршрутизация"),
        SimpleNamespace(id="path", path="notes/Readme.md", title="Different"),
    ]
    assert resolve_link(ExtractedLink("../notes/README.md", relative=True), "sub/index.md", docs).id == "path"
    assert resolve_link(ExtractedLink("VPN И МАРШРУТИЗАЦИЯ"), "index.md", docs).id == "title"
    assert resolve_link(ExtractedLink("Missing"), "index.md", docs) is None
    assert ghost_id("Missing") == "ghost:missing"
