from aihub_control.redaction import redact


def test_redacts_known_secrets_and_marks_change():
    value, changed = redact(
        {"output": "token=ghp_abc password=hunter2", "nested": {"x": "sk-test"}}
    )
    assert changed and "ghp_" not in str(value) and "sk-test" not in str(value)


def test_redacts_high_entropy_output():
    value, changed = redact({"output": "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"})
    assert changed and value["output"] == "[REDACTED]"


def test_does_not_redact_normal_text():
    value, changed = redact({"message": "hello world"})
    assert value["message"] == "hello world" and not changed


def test_redacts_whole_authorization_header():
    headers = ("Authorization: Bearer abc123", "authorization: Basic dXNlcjpwYXNz", "Proxy-Authorization: Token t0k")
    for header in headers:
        value, changed = redact({"output": f"> GET /api\n> {header}\n< 200 OK"})
        assert changed
        assert header.split()[-1] not in value["output"]
        assert "< 200 OK" in value["output"]


def test_redacts_whole_cookie_header():
    value, changed = redact({"output": "Cookie: session=secret; other=value\nnext line"})
    assert changed
    assert "secret" not in value["output"]
    assert "other=value" not in value["output"]
    assert "next line" in value["output"]


def test_file_paths_are_not_redacted():
    # Found on the first real Codex session: "/home/dev/projects/hello-hub/README.md" became "[REDACTED].md".
    for path in ("/home/dev/projects/hello-hub/README.md", "services/control-plane/aihub_control/redaction.py",
                 "/mnt/c/Users/Desktop/AI-Knowledge/INDEX.md"):
        value, changed = redact({"output": f"edited {path}"})
        assert value["output"] == f"edited {path}" and not changed


def test_words_with_sk_dash_are_not_keys():
    value, changed = redact({"output": "moved desk-top and task-runner configs"})
    assert value["output"] == "moved desk-top and task-runner configs" and not changed


def test_real_keys_are_still_redacted():
    samples = ["sk-proj-" + "aB3xK9mQ7vZ2pL8nR4tY6wE1", "sk-ant-api03-" + "Zq8Xv2Lm9Pt4Rk7Wn3Hs6Jd1",
               "base64 secret " + "aB3x/K9mQ7vZ2p/L8nR4tY6wE1uI5oPqWsXz"]
    for sample in samples:
        value, changed = redact({"output": sample})
        assert changed, sample
        assert "aB3x" not in value["output"] and "Zq8X" not in value["output"], value

