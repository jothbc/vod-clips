"""FastAPI job endpoints tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.jobs import JobManager, JobState, JobStatus


@pytest.fixture
def client(monkeypatch):
    import reels.jobs as jobs_mod

    jobs_mod._manager = JobManager()
    return TestClient(create_app())


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "ffmpeg" in data
    assert "ollama" in data


def test_create_job_invalid_path(client):
    r = client.post("/api/jobs", json={"video_path": "/nonexistent/vod.mp4"})
    assert r.status_code == 404


def test_validate_video_path_rejects_traversal():
    from reels.jobs import validate_video_path

    with pytest.raises(ValueError):
        validate_video_path("/tmp/../etc/passwd.mp4")


@patch.object(JobManager, "_run_job")
def test_create_job_success(mock_run, client, tmp_path):
    vod = tmp_path / "test.mp4"
    vod.write_bytes(b"\x00" * 100)

    r = client.post(
        "/api/jobs",
        json={
            "video_path": str(vod),
            "mode": "gaming",
            "preset": "twitch_gaming",
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    r2 = client.get(f"/api/jobs/{job_id}")
    assert r2.status_code == 200
    assert r2.json()["video_path"] == str(vod.resolve())


def test_get_job_not_found(client):
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_clips_empty_for_new_job(client, tmp_path):
    vod = tmp_path / "clip.mp4"
    vod.write_bytes(b"x")

    import reels.jobs as jobs_mod

    mgr = jobs_mod.get_job_manager()
    job_id = "test-job-id"
    out = tmp_path / "out"
    out.mkdir()
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vod),
        output_dir=str(out),
    )
    mgr._running = False

    r = client.get(f"/api/jobs/{job_id}/clips")
    assert r.status_code == 200
    assert r.json()["clips"] == []
