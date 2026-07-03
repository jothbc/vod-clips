"""Tests for GET /api/v2/videos/{id}/related."""

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


def _seed_vod(slug: str = "test_vod") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Test", kind="original", duration=120.0, size_bytes=100)
    )


def test_get_related_returns_clips_200(client):
    _seed_vod("vod_x")
    vs.save_clip_metadata(
        "vod_x",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_x",
            title="Highlight 1",
            start=10.0,
            end=30.0,
            formats=["youtube"],
        ),
    )
    r = client.get("/api/v2/videos/vod_x/related")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "clip"
    assert items[0]["start"] == 10.0
    assert "clips/clip_00" in items[0]["stream_url"]


def test_get_video_detail_composite_clip_id(client):
    _seed_vod("vod_z")
    vs.save_clip_metadata(
        "vod_z",
        ClipMetadata(
            clip_slug="clip_04",
            parent_slug="vod_z",
            title="My Clip",
            start=100.0,
            end=130.0,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id("vod_z", "clip_04")
    r = client.get(f"/api/v2/videos/{clip_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "clip"
    assert "clips/clip_04" in data["stream_url"]

    _seed_vod("vod_y")
    vs.save_clip_metadata(
        "vod_y",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_y",
            title="Clip",
            start=0.0,
            end=10.0,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id("vod_y", "clip_00")
    r = client.get(f"/api/v2/videos/{clip_id}/related")
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == "vod_y"
