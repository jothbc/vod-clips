"""Tests for video_store slug and metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import reels.video_store as vs
from reels.models import ClipMetadata, VideoMetadata


@pytest.fixture
def video_root(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    return vs.videos_root()


def test_make_unique_slug(video_root):
    slug = vs.make_unique_slug("My Stream.mp4")
    assert slug == "my_stream"
    vs.video_dir(slug).mkdir(parents=True)
    slug2 = vs.make_unique_slug("My Stream.mp4")
    assert slug2.startswith("my_stream_")


def test_create_and_list_video(video_root, monkeypatch):
    src = video_root.parent / "sample.mp4"
    src.write_bytes(b"\x00" * 2000)

    def fake_probe(path: Path):
        from reels.models import VideoInfo

        return VideoInfo(
            path=str(path),
            duration=120.0,
            width=1920,
            height=1080,
            fps=30.0,
            size_bytes=2000,
        )

    monkeypatch.setattr(vs, "probe_video", fake_probe)
    meta = vs.create_original_from_path(src, title="Sample")
    assert meta.slug
    assert vs.source_path(meta.slug).is_file()
    listed = vs.list_original_videos()
    assert len(listed) == 1
    assert listed[0].id == meta.slug


def test_slug_with_double_underscore_not_treated_as_clip(video_root):
    slug = "untitled_video_-_made_with_clipchamp__3"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 1000)
    meta = VideoMetadata(slug=slug, title="Clipchamp (3)", kind="original", duration=34.5)
    vs.save_metadata(meta)
    assert vs.get_video(slug) is not None
    assert vs.resolve_video_id(slug).slug == slug
    assert vs.stream_url_for(slug) == f"/api/v2/media/{slug}/source.mp4"


def test_clip_listing(video_root):
    slug = "test_vod"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 1000)
    meta = VideoMetadata(slug=slug, title="Test", kind="original", duration=60.0)
    vs.save_metadata(meta)
    vs.save_clip_metadata(
        slug,
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug=slug,
            title="Highlight",
            start=0.0,
            end=30.0,
            formats=["youtube", "reels"],
        ),
    )
    clip_dir = vs.clip_dir(slug, "clip_00")
    (clip_dir / "youtube.mp4").write_bytes(b"\x00" * 500)
    clips = vs.list_recent_clips()
    assert len(clips) == 1
    assert clips[0].parent_id == slug


def test_search_videos_matches_title_and_clip(video_root):
    slug = "test_vod"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 1000)
    meta = VideoMetadata(slug=slug, title="Summer Stream 2026", kind="original", duration=60.0)
    vs.save_metadata(meta)
    vs.save_clip_metadata(
        slug,
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug=slug,
            title="Epic Highlight",
            start=0.0,
            end=30.0,
            formats=["youtube"],
        ),
    )

    by_vod = vs.search_videos("summer")
    assert len(by_vod) == 1
    assert by_vod[0].kind == "original"

    by_clip = vs.search_videos("epic")
    assert len(by_clip) == 1
    assert by_clip[0].kind == "clip"
    assert by_clip[0].title == "Epic Highlight"

    assert vs.search_videos("missing") == []
