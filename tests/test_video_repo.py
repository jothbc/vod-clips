"""Tests for the DB-backed video registry: write-through, aliases, rename, publish."""

from __future__ import annotations

import pytest

from reels import video_repo
from reels.models import ClipMetadata, VideoMetadata
import reels.video_store as vs
from reels.video_store import (
    _to_storage_id,
    make_clip_id,
    save_clip_metadata,
    save_metadata,
    sync_from_filesystem,
)


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    return tmp_path


def _seed_vod(slug: str = "vod1", *, width: int = 1920, height: int = 1080) -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    save_metadata(
        VideoMetadata(
            slug=slug,
            title="Original",
            kind="original",
            duration=120.0,
            width=width,
            height=height,
            size_bytes=100,
        )
    )


def test_save_metadata_registers_vod(store):
    _seed_vod("vod1")
    rec = video_repo.get_by_slug("vod1")
    assert rec is not None
    assert rec.kind == "original"
    assert rec.title == "Original"
    assert rec.format == "desktop"  # landscape
    assert rec.storage_root == "video/vod1"


def test_portrait_vod_is_mobile_format(store):
    _seed_vod("vertical", width=1080, height=1920)
    rec = video_repo.get_by_slug("vertical")
    assert rec is not None
    assert rec.format == "mobile"


def test_clip_registered_with_parent_id(store):
    _seed_vod("parent")
    parent = video_repo.get_by_slug("parent")
    save_clip_metadata(
        "parent",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="parent",
            title="A clip",
            start=5.0,
            end=15.0,
            formats=["youtube", "reels"],
        ),
    )
    clip_id = make_clip_id("parent", "clip_00")
    rec = video_repo.resolve(clip_id)
    assert rec is not None
    assert rec.kind == "clip"
    assert rec.parent_id == parent.id
    assert rec.format == "desktop"  # youtube -> desktop
    assert rec.formats_available == ["youtube", "reels"]
    children = video_repo.children(parent.id)
    assert [c.slug for c in children] == [clip_id]


def test_resolve_by_uuid_and_alias(store):
    _seed_vod("vod1")
    rec = video_repo.get_by_slug("vod1")
    assert video_repo.resolve(rec.id).id == rec.id  # by uuid
    assert video_repo.resolve("vod1").id == rec.id  # by slug/alias


def test_rename_keeps_links_via_alias(store):
    _seed_vod("old_name")
    rec = video_repo.get_by_slug("old_name")
    renamed = video_repo.rename_video(rec.id, slug="new_name", title="New Title")
    assert renamed.slug == "new_name"
    assert renamed.title == "New Title"
    # Old slug still resolves to the same stable uuid.
    assert video_repo.resolve("old_name").id == rec.id
    assert video_repo.resolve("new_name").id == rec.id
    # Files never moved: storage identifier stays the original folder.
    assert _to_storage_id("new_name") == "old_name"


def test_to_storage_id_handles_absolute_windows_storage_root(store, monkeypatch):
    _seed_vod("vod1")
    abs_root = str((store / "video" / "vod1").resolve())
    monkeypatch.setattr(
        video_repo,
        "resolve",
        lambda _id: type(
            "R",
            (),
            {
                "kind": "original",
                "slug": "vod1",
                "storage_root": abs_root,
            },
        )(),
    )
    assert _to_storage_id("vod1") == "vod1"
    assert vs._parse_storage_parts(abs_root) == ("vod1", None)
    assert vs._parse_storage_parts(r"E:\projects\temp\video\twitch_123") == ("twitch_123", None)


def test_set_published(store):
    _seed_vod("vod1")
    rec = video_repo.get_by_slug("vod1")
    assert rec.published is False
    video_repo.set_published("vod1", True)
    assert video_repo.get_by_id(rec.id).published is True


def test_transcript_write_through_and_load(store):
    from reels.video_transcript import save_segments

    _seed_vod("vod1")
    segments = [{"start": 0.0, "end": 2.0, "text": "hello"}]
    save_segments("vod1", segments, original=True)
    loaded = video_repo.load_transcript("vod1")
    assert loaded is not None
    stored, original = loaded
    assert stored == segments
    assert original == segments
    assert video_repo.has_transcript("vod1") is True


def test_sync_from_filesystem_backfills(store):
    # Seed DB + disk, then write legacy JSON and wipe DB to simulate pre-migration data.
    _seed_vod("vodx")
    clip = ClipMetadata(clip_slug="clip_00", parent_slug="vodx", start=0.0, end=5.0, formats=["reels"])
    save_clip_metadata("vodx", clip)
    vs.metadata_path("vodx").write_text(
        VideoMetadata(
            slug="vodx",
            title="Original",
            kind="original",
            duration=120.0,
            width=1920,
            height=1080,
            size_bytes=100,
        ).model_dump_json(),
        encoding="utf-8",
    )
    vs.clip_meta_path("vodx", "clip_00").write_text(clip.model_dump_json(), encoding="utf-8")

    video_repo.delete_video("vodx")  # cascades to clip via parent_id
    assert video_repo.get_by_slug("vodx") is None

    result = sync_from_filesystem()
    assert result["vods"] == 1
    assert result["clips"] == 1
    assert result.get("orphans_recovered", 0) == 0
    assert video_repo.get_by_slug("vodx") is not None
    assert video_repo.resolve(make_clip_id("vodx", "clip_00")) is not None


def test_sync_recovers_orphan_clip_without_meta(store, monkeypatch):
    _seed_vod("vod_orphan")
    vs.metadata_path("vod_orphan").write_text(
        VideoMetadata(
            slug="vod_orphan",
            title="Original",
            kind="original",
            duration=120.0,
            width=1920,
            height=1080,
            size_bytes=100,
        ).model_dump_json(),
        encoding="utf-8",
    )

    orphan = vs.clip_dir("vod_orphan", "manual__01")
    orphan.mkdir(parents=True)
    (orphan / "youtube.mp4").write_bytes(b"\x00" * 50)

    empty = vs.clip_dir("vod_orphan", "empty_dir")
    empty.mkdir(parents=True)

    class _Info:
        duration = 12.5
        width = 1280
        height = 720
        fps = 30.0
        codec = "h264"
        size_bytes = 50

    monkeypatch.setattr(vs, "probe_video", lambda _path: _Info())

    result = sync_from_filesystem()
    assert result["orphans_recovered"] == 1
    assert result["orphans_removed"] >= 1
    assert video_repo.resolve(make_clip_id("vod_orphan", "manual__01")) is not None
    assert not empty.exists()
