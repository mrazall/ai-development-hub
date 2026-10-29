from pathlib import Path

from aihub_agents.worker import bring_claude_transcript

REF = "e1b6c8f7-db22-4238-a284-c46c7e56c113"


def _profile(home: Path, name: str) -> Path:
    path = home / ".aihub" / "accounts" / name / "claude"
    (path / "projects").mkdir(parents=True)
    return path


def test_copies_the_conversation_from_the_other_profile(tmp_path):
    a, b = _profile(tmp_path, "claude-main"), _profile(tmp_path, "claude-second")
    (a / "projects" / "-work").mkdir()
    (a / "projects" / "-work" / f"{REF}.jsonl").write_text("{}")
    (a / "projects" / "-work" / REF / "subagents").mkdir(parents=True)

    assert bring_claude_transcript(b, REF, home=tmp_path)
    assert (b / "projects" / "-work" / f"{REF}.jsonl").read_text() == "{}"
    assert (b / "projects" / "-work" / REF / "subagents").is_dir()
    assert (a / "projects" / "-work" / f"{REF}.jsonl").exists()  # copied, not moved
    assert not bring_claude_transcript(b, REF, home=tmp_path)  # already there


def test_nothing_to_do_or_unsafe_ref(tmp_path):
    b = _profile(tmp_path, "claude-second")
    assert not bring_claude_transcript(b, REF, home=tmp_path)
    assert not bring_claude_transcript(b, "../../etc/*", home=tmp_path)
