"""Tests for webcam region API and storage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import ClipMetadata, VideoMetadata, WebcamRegion
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


def _seed_landscape_vod(slug: str = "vod_cam") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 200)
    vs.save_metadata(
        VideoMetadata(
            slug=slug,
            title="Stream",
            kind="original",
            duration=120.0,
            width=1920,
            height=1080,
            size_bytes=200,
        )
    )


def test_put_and_get_webcam_region_on_vod(client, monkeypatch):
    slug = "vod_cam"
    _seed_landscape_vod(slug)
    monkeypatch.setattr(
        "reels.video_store.probe_video",
        lambda _p: type("I", (), {"duration": 120.0, "width": 1920, "height": 1080})(),
    )

    r = client.put(
        f"/api/v2/videos/{slug}/webcam-region",
        json={"x1": 1500, "y1": 700, "x2": 1900, "y2": 1060, "frame_at": 12.5},
    )
    assert r.status_code == 200
    data = r.json()["webcam_region"]
    assert data["x2"] > data["x1"]
    assert data["source_width"] == 1920

    detail = client.get(f"/api/v2/videos/{slug}").json()
    assert detail["webcam_eligible"] is True
    assert detail["has_webcam_region"] is True
    assert detail["webcam_region"]["x1"] == 1500


def test_delete_webcam_region(client, monkeypatch):
    slug = "vod_del"
    _seed_landscape_vod(slug)
    monkeypatch.setattr(
        "reels.video_store.probe_video",
        lambda _p: type("I", (), {"duration": 120.0, "width": 1920, "height": 1080})(),
    )
    client.put(
        f"/api/v2/videos/{slug}/webcam-region",
        json={"x1": 100, "y1": 100, "x2": 400, "y2": 400},
    )
    dr = client.delete(f"/api/v2/videos/{slug}/webcam-region")
    assert dr.status_code == 200
    detail = client.get(f"/api/v2/videos/{slug}").json()
    assert detail["webcam_region"] is None
    assert detail["has_webcam_region"] is False


def test_webcam_region_on_desktop_clip(client, monkeypatch):
    parent = "vod_clip_cam"
    clip_slug = "clip_01"
    _seed_landscape_vod(parent)
    clip_dir = vs.clip_dir(parent, clip_slug)
    clip_dir.mkdir(parents=True)
    (clip_dir / "youtube.mp4").write_bytes(b"\x00" * 100)
    vs.save_clip_metadata(
        parent,
        ClipMetadata(
            clip_slug=clip_slug,
            parent_slug=parent,
            title="Clip",
            start=0.0,
            end=30.0,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id(parent, clip_slug)
    monkeypatch.setattr(
        "reels.video_store.probe_video",
        lambda _p: type("I", (), {"duration": 30.0, "width": 1920, "height": 1080})(),
    )

    r = client.put(
        f"/api/v2/videos/{clip_id}/webcam-region",
        json={"x1": 10, "y1": 10, "x2": 300, "y2": 300},
    )
    assert r.status_code == 200

    meta = vs.load_clip_metadata(parent, clip_slug)
    assert meta is not None
    assert meta.webcam_region is not None
    assert meta.webcam_region.x2 == 300


def test_resolve_webcam_region_falls_back_to_parent(client, monkeypatch):
    parent = "vod_parent_cam"
    clip_slug = "clip_02"
    _seed_landscape_vod(parent)
    vs.save_metadata(
        vs.load_metadata(parent).model_copy(
            update={
                "webcam_region": WebcamRegion(
                    x1=10, y1=10, x2=200, y2=200, source_width=1920, source_height=1080
                )
            }
        )
    )
    clip_dir = vs.clip_dir(parent, clip_slug)
    clip_dir.mkdir(parents=True)
    (clip_dir / "youtube.mp4").write_bytes(b"\x00" * 100)
    vs.save_clip_metadata(
        parent,
        ClipMetadata(
            clip_slug=clip_slug,
            parent_slug=parent,
            title="Clip",
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id(parent, clip_slug)
    resolved = vs.resolve_webcam_region(clip_id)
    assert resolved is not None
    assert resolved.x2 == 200


def test_put_webcam_rejects_portrait_vod(client):
    slug = "vod_portrait"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 50)
    vs.save_metadata(
        VideoMetadata(
            slug=slug,
            title="Portrait",
            kind="original",
            width=1080,
            height=1920,
            duration=10.0,
            size_bytes=50,
        )
    )
    r = client.put(
        f"/api/v2/videos/{slug}/webcam-region",
        json={"x1": 0, "y1": 0, "x2": 100, "y2": 100},
    )
    assert r.status_code == 400
