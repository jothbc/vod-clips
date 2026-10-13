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


def test_delete_vod_removes_files_and_is_not_restored(video_root):
    from reels import video_repo

    slug = "vod_gone"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 1000)
    vs.save_metadata(VideoMetadata(slug=slug, title="Gone", kind="original", duration=10.0, size_bytes=1000))

    freed = vs.delete_video(slug)
    assert freed >= 1000
    assert not vs.video_dir(slug).exists()
    assert video_repo.resolve(slug) is None

    vs.sync_from_filesystem()
    assert video_repo.resolve(slug) is None
    assert not vs.video_dir(slug).exists()


def test_delete_vod_purges_db_when_folder_already_gone(video_root):
    import shutil

    from reels import video_repo

    slug = "vod_manual"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(VideoMetadata(slug=slug, title="Manual", kind="original", duration=10.0))
    shutil.rmtree(vs.video_dir(slug))

    assert vs.delete_video(slug) == 0
    assert video_repo.resolve(slug) is None


def test_delete_vod_removes_job_output_outside_video_tree(video_root, monkeypatch, tmp_path):
    from reels import job_store, video_repo

    monkeypatch.setattr(vs, "temp_root", lambda: tmp_path)
    slug = "vod_jobs"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 40)
    vs.save_metadata(VideoMetadata(slug=slug, title="Jobs", kind="original", duration=10.0, size_bytes=40))
    rec = video_repo.resolve(slug)
    assert rec is not None

    out = tmp_path / "outputs" / "job-1"
    out.mkdir(parents=True)
    (out / "export.mp4").write_bytes(b"\x00" * 80)
    job_store.insert_job(
        job_id="job-1",
        video_id=rec.id,
        feature="v2_captions",
        params={},
        params_hash="abc",
        status="completed",
        output_dir=str(out),
        created_at="2026-01-01T00:00:00+00:00",
    )

    vs.delete_video(slug)
    assert not out.exists()
    assert job_store.get_job("job-1") is None
    assert video_repo.resolve(slug) is None


def test_sync_prunes_row_when_folder_is_missing(video_root):
    import shutil

    from reels import video_repo

    slug = "vod_pruned"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 20)
    vs.save_metadata(VideoMetadata(slug=slug, title="Pruned", kind="original", duration=5.0))
    shutil.rmtree(vs.video_dir(slug))

    result = vs.sync_from_filesystem()
    assert result["orphans_pruned"] >= 1
    assert video_repo.resolve(slug) is None


def test_delete_path_raises_when_files_remain(tmp_path, monkeypatch):
    import reels.storage as storage

    target = tmp_path / "locked"
    target.mkdir()
    (target / "source.mp4").write_bytes(b"\x00" * 10)
    monkeypatch.setattr(storage, "_DELETE_ATTEMPTS", 1)

    def _leave_in_place(path, **_kwargs):
        return None

    monkeypatch.setattr(storage.shutil, "rmtree", _leave_in_place)
    with pytest.raises(OSError):
        storage.delete_path(target)
    assert target.is_dir()
    assert (target / "source.mp4").is_file()
