"""Tests for v2 async analyze/export job endpoints."""

from __future__ import annotations

from unittest.mock import patch

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


def _seed_video(slug: str = "test_vod") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 2000)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Test", kind="original", duration=60.0, size_bytes=2000)
    )


def test_analyze_highlights_returns_202(client):
    _seed_video()
    with patch("reels.jobs.JobManager.create_job") as mock_create:
        from reels.jobs import JobState

        mock_create.return_value = JobState(
            id="job-1",
            video_path=str(vs.source_path("test_vod")),
            output_dir=str(vs.analysis_dir("test_vod")),
            feature="v2_analyze",
            status="queued",
        )
        r = client.post("/api/v2/videos/test_vod/analyze-highlights", json={"max_clips": 8})
    assert r.status_code == 202
    assert r.json()["job_id"] == "job-1"
    req = mock_create.call_args[0][0]
    assert req.max_clips == 8


def test_analyze_highlights_default_max_clips(client):
    _seed_video()
    with patch("reels.jobs.JobManager.create_job") as mock_create:
        from reels.jobs import JobState

        mock_create.return_value = JobState(
            id="job-1",
            video_path=str(vs.source_path("test_vod")),
            output_dir=str(vs.analysis_dir("test_vod")),
            feature="v2_analyze",
            status="queued",
        )
        r = client.post("/api/v2/videos/test_vod/analyze-highlights")
    assert r.status_code == 202
    req = mock_create.call_args[0][0]
    assert req.max_clips == 15


def test_get_highlights_404_when_missing(client):
    _seed_video()
    r = client.get("/api/v2/videos/test_vod/highlights")
    assert r.status_code == 404


def test_generate_clips_returns_202(client):
    _seed_video()
    with patch("reels.jobs.JobManager.create_job") as mock_create:
        from reels.jobs import JobState

        mock_create.return_value = JobState(
            id="job-2",
            video_path=str(vs.source_path("test_vod")),
            output_dir=str(vs.analysis_dir("test_vod")),
            feature="v2_export_clips",
            status="queued",
        )
        body = {
            "selections": [
                {
                    "index": 0,
                    "start": 0,
                    "end": 10,
                    "title": "Clip",
                    "export_youtube": True,
                    "export_reels": False,
                }
            ]
        }
        r = client.post("/api/v2/videos/test_vod/generate-clips", json=body)
    assert r.status_code == 202
    assert r.json()["job_id"] == "job-2"
