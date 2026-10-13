"""Tests for stream_url_for and related_videos."""

from __future__ import annotations

import json

import pytest

from reels.models import ClipMetadata, VideoMetadata
from reels.video_store import (
    CLIP_ID_SEP,
    make_clip_id,
    related_videos,
    save_clip_metadata,
    save_metadata,
    source_path,
    stream_url_for,
)
import reels.video_store as vs


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    return tmp_path


def _seed_vod(slug: str = "test_vod") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    save_metadata(
        VideoMetadata(slug=slug, title="Test VOD", kind="original", duration=120.0, size_bytes=100)
    )


def test_stream_url_for_composite_clip_id(store):
    _seed_vod("my_vod")
    clip_id = make_clip_id("my_vod", "clip_00")
    url = stream_url_for(clip_id, "youtube")
    assert url == "/api/v2/media/my_vod/clips/clip_00/youtube.mp4"
    url_reels = stream_url_for(clip_id, "reels")
    assert url_reels == "/api/v2/media/my_vod/clips/clip_00/reels.mp4"


def test_stream_url_for_composite_does_not_raise(store):
    _seed_vod()
    clip_id = f"test_vod{CLIP_ID_SEP}clip_01"
    # Should not raise ValueError from video_dir slug validation
    assert "clips/clip_01" in stream_url_for(clip_id)


def test_related_videos_lists_clips_sorted(store):
    _seed_vod("vod_a")
    save_clip_metadata(
        "vod_a",
        ClipMetadata(
            clip_slug="clip_01",
            parent_slug="vod_a",
            title="Later",
            start=60.0,
            end=90.0,
            formats=["youtube"],
        ),
    )
    save_clip_metadata(
        "vod_a",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_a",
            title="Earlier",
            start=10.0,
            end=40.0,
            formats=["youtube", "reels"],
        ),
    )

    items = related_videos("vod_a")
    assert len(items) == 2
    assert items[0].title == "Earlier"
    assert items[0].start == 10.0
    assert items[0].formats == ["youtube", "reels"]
    assert items[1].title == "Later"


def test_related_videos_clip_returns_parent(store):
    _seed_vod("vod_b")
    save_clip_metadata(
        "vod_b",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_b",
            title="Clip",
            start=0.0,
            end=10.0,
            formats=["youtube"],
        ),
    )
    clip_id = make_clip_id("vod_b", "clip_00")
    items = related_videos(clip_id)
    assert len(items) == 1
    assert items[0].kind == "original"
    assert items[0].id == "vod_b"
