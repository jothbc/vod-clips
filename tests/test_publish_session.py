"""Publish compose session and per-field suggest API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import VideoMetadata
from reels.publish_session import create_session, get_session, update_draft
import reels.video_store as vs


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(storage_mod, "temp_root", lambda: tmp_path / "temp")
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    (tmp_path / "temp").mkdir(parents=True)
    vs.videos_root().mkdir(parents=True)
    return TestClient(create_app())


@pytest.fixture
def video_with_transcript(tmp_path):
    slug = "vod_sess"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 80)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="VOD", kind="original", duration=60.0, size_bytes=80)
    )
    vs.transcript_dir(slug).mkdir(parents=True, exist_ok=True)
    segments = [{"start": 0, "end": 5, "text": "Momento épico no jogo"}]
    vs.segments_path(slug).write_text(json.dumps(segments), encoding="utf-8")
    return slug


def test_create_session_and_draft(tmp_path, monkeypatch):
    monkeypatch.setattr("reels.publish_session.temp_root", lambda: tmp_path / "temp")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    session = create_session(video_id="vid1", video_path=video)
    assert get_session(session.id) is not None
    update_draft(session.id, title="T", description="D", tags=["a"], platform="youtube")
    from reels.publish import load_publish

    doc = load_publish(session.output_dir / "manifest.json")
    assert doc.items[0].title == "T"
    assert doc.items[0].tags == ["a"]


def test_post_publish_session_api(client, video_with_transcript):
    r = client.post(f"/api/v2/videos/{video_with_transcript}/publish/session", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"]
    assert data["video_id"] == video_with_transcript


def test_suggest_title_field(client, video_with_transcript, monkeypatch):
    r = client.post(f"/api/v2/videos/{video_with_transcript}/publish/session", json={})
    session_id = r.json()["session_id"]

    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    mock_client.chat_text.return_value = json.dumps({"title": "Título IA"})

    with patch("reels.vlm.ollama.OllamaClient", return_value=mock_client):
        with patch("reels.api.videos.probe_video") as probe:
            probe.return_value = MagicMock(duration=60.0, height=1080, width=1920)
            sr = client.post(
                f"/api/v2/publish/sessions/{session_id}/suggest",
                json={"field": "title", "platform": "youtube", "content_type": "game", "game_name": "Zelda"},
            )
    assert sr.status_code == 200
    assert sr.json()["title"] == "Título IA"


def test_suggest_requires_transcript(client, tmp_path):
    slug = "no_tx"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 10)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="X", kind="original", duration=10.0, size_bytes=10)
    )
    r = client.post(f"/api/v2/videos/{slug}/publish/session", json={})
    session_id = r.json()["session_id"]
    sr = client.post(
        f"/api/v2/publish/sessions/{session_id}/suggest",
        json={"field": "title"},
    )
    assert sr.status_code == 400


def test_deploy_accepts_session_id(client, video_with_transcript, monkeypatch, tmp_path):
    import reels.publish_wallet as pw

    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args

        def start(self):
            if self._target:
                self._target(*self._args)

    monkeypatch.setattr("reels.api.publish_wallet.threading.Thread", _SyncThread)

    tr = client.post(
        "/api/v2/publish/targets",
        json={"label": "YT", "platform": "youtube", "config": {"privacy": "unlisted"}},
    )
    target_id = tr.json()["id"]

    sr = client.post(f"/api/v2/videos/{video_with_transcript}/publish/session", json={})
    session_id = sr.json()["session_id"]

    from reels.publish_session import get_session, update_draft

    update_draft(session_id, title="T", description="D", tags=["g"], platform="youtube")

    with patch("reels.api.publish_wallet.load_credentials") as lc:
        lc.return_value = {"access_token": "tok", "refresh_token": ""}
        with patch("reels.api.publish_wallet.upload_video", return_value="yt123") as up:
            dr = client.post(
                "/api/v2/publish/deploy",
                json={
                    "session_id": session_id,
                    "target_id": target_id,
                    "overrides": {"title": "T", "description": "D", "tags": ["g"], "youtube_format": "shorts"},
                },
            )
    assert dr.status_code == 200
    deploy_id = dr.json()["deploy_id"]
    status = client.get(f"/api/v2/publish/deploy/{deploy_id}").json()
    assert status["status"] == "completed"
    assert status["platform_post_id"] == "yt123"
    up.assert_called_once()
    assert up.call_args.kwargs.get("youtube_format") == "shorts"
    session = get_session(session_id)
    assert session is not None


def test_deploy_failure_with_session_records_history(client, video_with_transcript, monkeypatch, tmp_path):
    import reels.publish_wallet as pw

    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args

        def start(self):
            if self._target:
                self._target(*self._args)

    monkeypatch.setattr("reels.api.publish_wallet.threading.Thread", _SyncThread)

    tr = client.post(
        "/api/v2/publish/targets",
        json={
            "label": "YT",
            "platform": "youtube",
            "config": {"oauth_client_id": "cid", "oauth_client_secret": "sec"},
        },
    )
    target_id = tr.json()["id"]
    pw.save_credentials(target_id, access_token="tok", refresh_token="ref")

    from reels.publish_session import update_draft

    sr = client.post(f"/api/v2/videos/{video_with_transcript}/publish/session", json={})
    session_id = sr.json()["session_id"]
    update_draft(session_id, title="T", description="D", tags=[], platform="youtube")

    with patch("reels.api.publish_wallet.load_credentials") as lc:
        lc.return_value = {"access_token": "tok", "refresh_token": "ref"}
        with patch("reels.api.publish_wallet.upload_video", side_effect=RuntimeError("YouTube API (403): denied")):
            dr = client.post(
                "/api/v2/publish/deploy",
                json={"session_id": session_id, "target_id": target_id, "overrides": {"title": "T"}},
            )
    assert dr.status_code == 200
    deploy_id = dr.json()["deploy_id"]
    status = client.get(f"/api/v2/publish/deploy/{deploy_id}").json()
    assert status["status"] == "failed"
    assert "YouTube API" in status["error"]


def test_upload_session_thumbnail(client, video_with_transcript, tmp_path, monkeypatch):
    import reels.publish_session as ps

    monkeypatch.setattr(ps, "temp_root", lambda: tmp_path / "temp")
    sr = client.post(f"/api/v2/videos/{video_with_transcript}/publish/session", json={})
    session_id = sr.json()["session_id"]

    jpeg = b"\xff\xd8\xff\xd9"
    r = client.post(
        f"/api/v2/publish/sessions/{session_id}/thumbnail",
        files={"file": ("thumb.jpg", jpeg, "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.json()["thumbnail_url"]

    gr = client.get(f"/api/v2/publish/sessions/{session_id}/thumbnail")
    assert gr.status_code == 200
