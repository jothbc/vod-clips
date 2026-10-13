"""Upload API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod
    import reels.video_store as vs_mod
    from reels.models import VideoInfo

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")

    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(
        vs_mod,
        "probe_video",
        lambda path: VideoInfo(
            path=str(path),
            duration=60.0,
            width=1280,
            height=720,
            fps=30.0,
            size_bytes=path.stat().st_size if path.is_file() else 0,
        ),
    )
    return TestClient(create_app())


def test_upload_mp4_stream(client, tmp_path):
    r = client.post(
        "/api/upload",
        files={"file": ("vod.mp4", b"\x00" * 5000, "video/mp4")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["size_bytes"] == 5000
    assert Path(data["path"]).exists()
    assert "video" in data["path"]
    assert data.get("video_id")
