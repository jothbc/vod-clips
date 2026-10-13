"""Shared API endpoint tests (health, twitch download)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.jobs import JobManager


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


def test_validate_video_path_rejects_traversal():
    from reels.jobs import validate_video_path

    with pytest.raises(ValueError):
        validate_video_path("/tmp/../etc/passwd.mp4")


def test_twitch_download_invalid_url(client):
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
