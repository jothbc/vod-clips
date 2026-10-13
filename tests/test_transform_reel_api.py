"""Tests for transform-reel API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import ClipMetadata, VideoMetadata
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


def _seed_clip(parent: str = "vod_reel", clip_slug: str = "clip_01") -> str:
    vs.original_dir(parent).mkdir(parents=True)
    vs.source_path(parent).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=parent, title="Parent", kind="original", duration=120.0, size_bytes=100)
    )
    clip_dir = vs.clip_dir(parent, clip_slug)
    clip_dir.mkdir(parents=True)
    (clip_dir / "youtube.mp4").write_bytes(b"\x00" * 80)
    vs.save_clip_metadata(
        parent,
        ClipMetadata(
            clip_slug=clip_slug,
            parent_slug=parent,
            title="Desktop clip",
            start=10.0,
            end=40.0,
            formats=["youtube"],
            source_feature="highlight",
        ),
    )
    return vs.make_clip_id(parent, clip_slug)


def test_post_transform_reel_accepts_desktop_clip(client, monkeypatch):
    clip_id = _seed_clip()
    monkeypatch.setattr(
        "reels.api.videos.probe_video",
        lambda _p: type("I", (), {"duration": 30.0, "width": 1920, "height": 1080})(),
    )

    class FakeState:
        id = "job_reel_1"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            assert req.feature == "v2_transform_reel"
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(f"/api/v2/videos/{clip_id}/transform-reel", json={})
    assert r.status_code == 202
    assert r.json()["job_id"] == "job_reel_1"


def test_post_transform_reel_passes_include_webcam(client, monkeypatch):
    clip_id = _seed_clip()
    monkeypatch.setattr(
        "reels.api.videos.probe_video",
        lambda _p: type("I", (), {"duration": 30.0, "width": 1920, "height": 1080})(),
    )

    class FakeState:
        id = "job_reel_cam"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            assert req.feature == "v2_transform_reel"
            assert req.params.get("include_webcam") is True
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(f"/api/v2/videos/{clip_id}/transform-reel", json={"include_webcam": True})
    assert r.status_code == 202


def test_post_transform_reel_accepts_landscape_vod(client, monkeypatch):
    slug = "vod_recorte"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 50)
    vs.save_metadata(
        VideoMetadata(
            slug=slug,
            title="Recorte VOD",
            kind="original",
            duration=25.0,
            width=1920,
            height=1080,
            size_bytes=50,
        )
    )
    monkeypatch.setattr(
        "reels.api.videos.probe_video",
        lambda _p: type("I", (), {"duration": 25.0, "width": 1920, "height": 1080})(),
    )

    class FakeState:
        id = "job_reel_vod"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            assert req.feature == "v2_transform_reel"
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(f"/api/v2/videos/{slug}/transform-reel", json={})
    assert r.status_code == 202
    assert r.json()["job_id"] == "job_reel_vod"


def test_post_transform_reel_rejects_portrait_vod(client):
    slug = "vod_portrait"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 50)
    vs.save_metadata(
        VideoMetadata(
            slug=slug,
            title="Portrait",
            kind="original",
            duration=15.0,
            width=1080,
            height=1920,
            size_bytes=50,
        )
    )
    r = client.post(f"/api/v2/videos/{slug}/transform-reel", json={})
    assert r.status_code == 400
    assert "vertical" in r.json()["detail"].lower() or "landscape" in r.json()["detail"].lower()


def test_post_transform_reel_rejects_clip_without_youtube(client):
    parent = "vod_no_yt"
    clip_slug = "clip_x"
    vs.original_dir(parent).mkdir(parents=True)
    vs.source_path(parent).write_bytes(b"\x00" * 50)
    vs.save_metadata(
        VideoMetadata(slug=parent, title="Parent", kind="original", duration=60.0, size_bytes=50)
    )
    clip_dir = vs.clip_dir(parent, clip_slug)
    clip_dir.mkdir(parents=True)
    (clip_dir / "reels.mp4").write_bytes(b"\x00" * 40)
    vs.save_clip_metadata(
        parent,
        ClipMetadata(
            clip_slug=clip_slug,
            parent_slug=parent,
            title="Mobile only",
            start=0.0,
            end=15.0,
            formats=["reels"],
            source_feature="highlight",
        ),
    )
    clip_id = vs.make_clip_id(parent, clip_slug)
    r = client.post(f"/api/v2/videos/{clip_id}/transform-reel", json={})
    assert r.status_code == 400
    assert "youtube" in r.json()["detail"].lower() or "desktop" in r.json()["detail"].lower()
