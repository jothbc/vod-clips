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
    import reels.twitch.manager as twitch_mod

    jobs_mod._manager = JobManager()
    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    c = TestClient(create_app())
    yield c
    jobs_mod.get_job_manager()._running = False


def test_ready(client):
    r = client.get("/api/ready")
    assert r.status_code == 200
    assert r.json()["ok"] is True


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
    def finish_job(job_id, video, out, req):
        import reels.jobs as jobs_mod

        with jobs_mod.get_job_manager()._lock:
            jobs_mod.get_job_manager()._running = False

    mock_run.side_effect = finish_job

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


def test_highlights_not_ready(client):
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000/highlights")
    assert r.status_code == 404


def test_source_video_not_found(client):
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000/source")
    assert r.status_code == 404


def test_reset_session(client):
    r = client.post("/api/session/reset", json={})
    assert r.status_code == 200
    assert r.json().get("cancelled") is True


def test_features_endpoint(client):
    r = client.get("/api/features")
    assert r.status_code == 200
    ids = {f["id"] for f in r.json()["features"]}
    assert {"reels", "cleanup", "twitch_download", "reels_library", "captions", "publish"} <= ids


def test_cancel_unknown_job_404(client):
    r = client.post("/api/jobs/00000000-0000-0000-0000-000000000000/cancel")
    assert r.status_code == 404


def test_cancel_running_job_marks_cancelling(client, tmp_path):
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()

    import reels.jobs as jobs_mod

    mgr = jobs_mod.get_job_manager()
    job_id = "cancel-test-job"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.RUNNING,
        video_path=str(vod),
        output_dir=str(out),
    )

    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["phase"] == "cancelling"
    mgr._running = False


def test_export_requires_completed_job(client, tmp_path):
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()

    import reels.jobs as jobs_mod

    mgr = jobs_mod.get_job_manager()
    job_id = "export-test-job"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.RUNNING,
        video_path=str(vod),
        output_dir=str(out),
    )
    mgr._running = False

    r = client.post(
        f"/api/jobs/{job_id}/export",
        json={"highlight_indices": [0]},
    )
    assert r.status_code == 409


def test_twitch_download_invalid_url(client):
    import reels.jobs as jobs_mod
    import reels.twitch.manager as twitch_mod

    jobs_mod.get_job_manager()._running = False
    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)

    with patch("reels.api.app.require_yt_dlp", return_value="/usr/bin/yt-dlp"):
        r = client.post("/api/twitch/download", json={"url": "https://example.com/not-twitch"})
    assert r.status_code == 400


@patch("reels.api.app.require_yt_dlp")
def test_twitch_download_starts(mock_yt, client):
    import reels.twitch.manager as twitch_mod

    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    mock_yt.return_value = "/usr/bin/yt-dlp"

    with patch.object(twitch_mod.TwitchDownloadManager, "_run"):
        r = client.post(
            "/api/twitch/download",
            json={"url": "https://www.twitch.tv/videos/2783991554"},
        )
    assert r.status_code == 200
    assert "download_id" in r.json()


@patch("reels.api.app.require_yt_dlp")
def test_twitch_download_not_blocked_by_analysis_job(mock_yt, client):
    import reels.jobs as jobs_mod
    import reels.twitch.manager as twitch_mod

    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    jobs_mod.get_job_manager()._running = True
    mock_yt.return_value = "/usr/bin/yt-dlp"

    with patch.object(twitch_mod.TwitchDownloadManager, "_run"):
        r = client.post(
            "/api/twitch/download",
            json={"url": "https://www.twitch.tv/videos/2783991555"},
        )
    assert r.status_code == 200
    jobs_mod.get_job_manager()._running = False


@patch("reels.api.app.require_yt_dlp")
def test_twitch_download_batch_and_list(mock_yt, client):
    import reels.twitch.manager as twitch_mod

    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    mock_yt.return_value = "/usr/bin/yt-dlp"

    with patch.object(twitch_mod.TwitchDownloadManager, "_run"):
        r = client.post(
            "/api/twitch/download/batch",
            json={
                "urls": [
                    "https://www.twitch.tv/videos/5001",
                    "https://www.twitch.tv/videos/5002",
                ]
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert len(data["download_ids"]) == 2
    assert len(data["downloads"]) == 2

    listed = client.get("/api/twitch/downloads")
    assert listed.status_code == 200
    assert len(listed.json()["downloads"]) >= 2


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
