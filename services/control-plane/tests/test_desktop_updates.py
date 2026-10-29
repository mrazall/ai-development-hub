import json

from fastapi.testclient import TestClient
from test_api_integration import app  # sets the test environment before the app loads

from aihub_control import main


def test_latest_json_points_at_the_hub_and_files_are_served(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(main.settings, "public_url", "https://hub.test/")
    client = TestClient(app)
    assert client.get("/desktop/latest.json").status_code == 404

    releases = tmp_path / "desktop"
    releases.mkdir()
    name = "AI Development Hub_0.2.0_x64-setup.exe"
    (releases / name).write_bytes(b"MZ")
    (releases / "latest.json").write_text(json.dumps({
        "version": "0.2.0", "platforms": {"windows-x86_64": {"signature": "sig", "url": name}},
    }))
    latest = client.get("/desktop/latest.json").json()
    assert latest["platforms"]["windows-x86_64"]["url"] == f"https://hub.test/desktop/{name}"
    assert client.get(f"/desktop/{name}").content == b"MZ"
    assert client.get("/desktop/latest.json.bak").status_code == 404
    assert client.get("/desktop/..%2F..%2Fetc%2Fpasswd").status_code == 404
