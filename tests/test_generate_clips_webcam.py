"""Tests for generate-clips include_webcam parameter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import VideoMetadata
import reels.video_store as vs


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    return TestClient(create_app())


def test_generate_clips_forwards_include_webcam(client, monkeypatch):
    slug = "vod_export_cam"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(
            slug=slug,
            title="VOD",
            kind="original",
            duration=60.0,
            width=1920,
            height=1080,
            size_bytes=100,
        )
    )

    class FakeState:
        id = "job_export"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            assert req.feature == "v2_export_clips"
            sel = req.params["selections"][0]
            assert sel["include_webcam"] is True
            assert sel["export_reels"] is True
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(
        f"/api/v2/videos/{slug}/generate-clips",
        json={
            "selections": [
                {
                    "index": 0,
                    "start": 0,
                    "end": 10,
                    "title": "H",
                    "export_youtube": False,
                    "export_reels": True,
                    "include_webcam": True,
                }
            ]
        },
    )
    assert r.status_code == 202
