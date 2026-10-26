from aihub_control.routers.attachments import _valid_signature, safe_filename


def test_attachment_filename_is_basename_and_strips_controls():
    assert safe_filename("../../notes\n.txt") == "notes_.txt"
    assert "/" not in safe_filename("dir/name.md")


def test_attachment_signatures_match_declared_mime():
    assert _valid_signature("image/png", b"\x89PNG\r\n\x1a\nrest")
    assert _valid_signature("application/pdf", b"%PDF-1.7")
    assert not _valid_signature("image/png", b"not an image")
    assert not _valid_signature("application/pdf", b"plain text")
