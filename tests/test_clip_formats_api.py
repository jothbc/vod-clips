"""Tests for clip format API and registration helpers."""

from __future__ import annotations

import json

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
    (root / "config" / "cleanup.yaml").write_text("preset: cleanup\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    return TestClient(create_app())


def _seed_vod(slug: str = "vod_fmt") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Test VOD", kind="original", duration=120.0, size_bytes=100)
    )


def test_register_clip_from_files(client):
    _seed_vod("vod_fmt")
    tmp_src = vs.videos_root().parent / "caption_src.mp4"
    tmp_src.write_bytes(b"\x00" * 50)
    clip, clip_id = vs.register_clip_from_files(
        "vod_fmt",
        title="Legendas — Test",
        start=0.0,
        end=60.0,
        source_feature="captions",
        files={"reels": tmp_src},
    )
    assert clip.source_feature == "captions"
    assert clip_id.startswith("vod_fmt::caption_")


def test_clip_detail_includes_stream_urls(client):
    _seed_vod("vod_y")
    vs.save_clip_metadata(
        "vod_y",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_y",
            title="Dual",
            start=0.0,
            end=30.0,
            formats=["youtube", "reels"],
        ),
    )
    d = vs.clip_dir("vod_y", "clip_00")
    (d / "youtube.mp4").write_bytes(b"\x00" * 10)
    (d / "reels.mp4").write_bytes(b"\x00" * 10)
    clip_id = vs.make_clip_id("vod_y", "clip_00")
    r = client.get(f"/api/v2/videos/{clip_id}")
    assert r.status_code == 200
    data = r.json()
    assert set(data["formats"]) == {"youtube", "reels"}
    assert "youtube" in data["stream_urls"]
    assert "reels" in data["stream_urls"]


def test_list_clips_expands_formats(client):
    _seed_vod("vod_z")
    vs.save_clip_metadata(
        "vod_z",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_z",
            title="Dual clip",
            start=0.0,
            end=30.0,
            formats=["youtube", "reels"],
        ),
    )
    d = vs.clip_dir("vod_z", "clip_00")
    (d / "youtube.mp4").write_bytes(b"\x00" * 10)
    (d / "reels.mp4").write_bytes(b"\x00" * 10)
    r = client.get("/api/v2/clips?limit=20")
    assert r.status_code == 200
    formats = {c["format"] for c in r.json()["clips"] if c["id"].endswith("clip_00")}
    assert formats == {"youtube", "reels"}


def test_make_derived_clip_slug(client):
    _seed_vod("vod_der")
    slug = vs.make_derived_clip_slug("vod_der", "clip_04", "skip_silence")
    assert slug == "clip_04_skip_silence"
    vs.clip_dir("vod_der", slug).mkdir(parents=True)
    slug2 = vs.make_derived_clip_slug("vod_der", "clip_04", "skip_silence")
    assert slug2 == "clip_04_skip_silence_02"


def test_post_cleanup_from_clip_uses_clip_file(client, monkeypatch):
    _seed_vod("vod_clip_job")
    vs.save_clip_metadata(
        "vod_clip_job",
        ClipMetadata(
            clip_slug="clip_04",
            parent_slug="vod_clip_job",
            title="Highlight @ 1050s",
            start=100.0,
            end=125.0,
            formats=["youtube"],
        ),
    )
    clip_path = vs.clip_dir("vod_clip_job", "clip_04")
    (clip_path / "youtube.mp4").write_bytes(b"\x00" * 100)
    vs.transcript_dir("vod_clip_job").mkdir(parents=True)
    vs.segments_path("vod_clip_job").write_text("[]", encoding="utf-8")

    captured: dict = {}

    def fake_create_job(req):
        captured["video_path"] = req.video_path
        captured["params"] = req.params
        from reels.jobs import JobState, JobStatus

        return JobState(
            id="job_test",
            feature=req.feature,
            status=JobStatus.RUNNING,
            video_path=req.video_path,
            output_dir=req.output_dir,
            preset=req.preset,
        )

    import reels.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod.get_job_manager(), "create_job", fake_create_job)
    clip_id = vs.make_clip_id("vod_clip_job", "clip_04")
    r = client.post(
        f"/api/v2/videos/{clip_id}/cleanup",
        json={"export_youtube": True, "export_reels": False, "source_format": "youtube"},
    )
    assert r.status_code == 202
    assert r.json()["video_id"] == clip_id
    assert captured["params"]["source_clip_slug"] == "clip_04"
    assert captured["params"]["clip_start"] == 100.0
    assert captured["params"]["clip_end"] == 125.0
    assert captured["video_path"].endswith("clip_04\\youtube.mp4") or captured["video_path"].endswith(
        "clip_04/youtube.mp4"
    )


def test_config_endpoints(client):
    r1 = client.get("/api/v2/config/captions")
    assert r1.status_code == 200
    assert "fonts" in r1.json()
    r2 = client.get("/api/v2/config/cleanup")
    assert r2.status_code == 200
    assert "defaults" in r2.json()


def test_delete_clip(client):
    _seed_vod("vod_del_clip")
    vs.save_clip_metadata(
        "vod_del_clip",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_del_clip",
            title="To delete",
            start=0.0,
            end=10.0,
            formats=["youtube"],
        ),
    )
    d = vs.clip_dir("vod_del_clip", "clip_00")
    (d / "youtube.mp4").write_bytes(b"\x00" * 10)
    clip_id = vs.make_clip_id("vod_del_clip", "clip_00")
    r = client.delete(f"/api/v2/videos/{clip_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert not d.exists()
    assert vs.video_dir("vod_del_clip").is_dir()


def test_delete_vod_removes_entire_tree(client):
    _seed_vod("vod_del_all")
    vs.save_clip_metadata(
        "vod_del_all",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_del_all",
            title="Child",
            start=0.0,
            end=10.0,
            formats=["youtube"],
        ),
    )
    r = client.delete("/api/v2/videos/vod_del_all")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert not vs.video_dir("vod_del_all").exists()
