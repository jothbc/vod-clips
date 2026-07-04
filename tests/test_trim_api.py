"""Tests for manual trim span validation and API."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.jobs import JobManager, JobState, JobStatus
from reels.models import VideoMetadata
from reels.trim import validate_keep_spans
import reels.jobs as jobs_mod
import reels.video_store as vs


def test_validate_keep_spans_ok():
    kept = validate_keep_spans([[0, 10], [15, 30]], 60.0)
    assert kept == [(0.0, 10.0), (15.0, 30.0)]


def test_validate_keep_spans_preserves_order_and_duplicates():
    kept = validate_keep_spans([[20, 40], [0, 10], [0, 10]], 60.0)
    assert kept == [(20.0, 40.0), (0.0, 10.0), (0.0, 10.0)]


def test_validate_keep_spans_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        validate_keep_spans([], 60.0)


def test_validate_keep_spans_rejects_out_of_range():
    with pytest.raises(ValueError, match="out of range"):
        validate_keep_spans([[0, 70]], 60.0)


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


def _seed_vod(slug: str = "vod_trim") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Trim VOD", kind="original", duration=120.0, size_bytes=100)
    )


def test_post_trim_accepts_duplicate_spans(client, monkeypatch):
    _seed_vod("vod_trim3")
    monkeypatch.setattr(
        "reels.api.videos.probe_video",
        lambda _p: type("I", (), {"duration": 120.0, "width": 1920, "height": 1080})(),
    )

    class FakeState:
        id = "job_trim_dup"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(
        "/api/v2/videos/vod_trim3/trim",
        json={"keep_spans": [[0, 10], [0, 10]]},
    )
    assert r.status_code == 202


def test_post_trim_rejects_invalid_spans(client, monkeypatch):
    _seed_vod("vod_trim")
    monkeypatch.setattr(
        "reels.api.videos.probe_video",
        lambda _p: type("I", (), {"duration": 120.0, "width": 1920, "height": 1080})(),
    )
    r = client.post(
        "/api/v2/videos/vod_trim/trim",
        json={"keep_spans": [[0, 0.1]]},
    )
    assert r.status_code == 400


def test_post_trim_accepts_valid_spans(client, monkeypatch):
    _seed_vod("vod_trim2")
    monkeypatch.setattr(
        "reels.api.videos.probe_video",
        lambda _p: type("I", (), {"duration": 120.0, "width": 1920, "height": 1080})(),
    )

    class FakeState:
        id = "job_trim_1"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(
        "/api/v2/videos/vod_trim2/trim",
        json={"keep_spans": [[0, 10], [20, 40]]},
    )
    assert r.status_code == 202
    data = r.json()
    assert data["job_id"] == "job_trim_1"


def test_replace_original_vod_source(tmp_path, monkeypatch):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)

    slug = "vod_rep"
    vs.original_dir(slug).mkdir(parents=True)
    original = vs.source_path(slug)
    original.write_bytes(b"\x00" * 80)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Orig", kind="original", duration=120.0, size_bytes=80)
    )
    vs.segments_path(slug).parent.mkdir(parents=True, exist_ok=True)
    vs.segments_path(slug).write_text("[]", encoding="utf-8")

    new_src = tmp_path / "trimmed.mp4"
    new_src.write_bytes(b"\x00" * 120)
    monkeypatch.setattr(
        "reels.video_store.probe_video",
        lambda _p: type("I", (), {
            "duration": 45.0,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "codec": "h264",
            "size_bytes": 120,
        })(),
    )

    meta = vs.replace_original_vod_source(slug, new_src)
    assert meta.duration == 45.0
    assert vs.source_path(slug).read_bytes() == new_src.read_bytes()
    assert not vs.segments_path(slug).is_file()


def test_register_trim_as_vod(tmp_path, monkeypatch):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)

    src = tmp_path / "trimmed.mp4"
    src.write_bytes(b"\x00" * 200)
    monkeypatch.setattr(
        "reels.video_store.probe_video",
        lambda _p: type("I", (), {
            "duration": 42.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "codec": "h264",
            "size_bytes": 200,
        })(),
    )

    meta, vod_id = vs.register_trim_as_vod(src, title="recorte — Test", slug_base="vod_x_recorte")
    assert meta.kind == "original"
    assert vod_id == meta.slug
    assert vod_id.startswith("vod_x_recorte")
    assert vs.source_path(vod_id).is_file()


def test_finalize_trim_new_clip(tmp_path, monkeypatch):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)

    slug = "vod_clip_trim"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Trim VOD", kind="original", duration=120.0, size_bytes=100)
    )

    trim_path = tmp_path / "trimmed.mp4"
    trim_path.write_bytes(b"\x00" * 150)
    out = tmp_path / "out"
    out.mkdir()
    ctx = {
        "source_video_id": slug,
        "keep_spans": [[0, 10], [20, 30]],
        "trim_output_path": str(trim_path),
    }
    (out / "v2_job_context.json").write_text(json.dumps(ctx), encoding="utf-8")

    jobs_mod._manager = JobManager()
    mgr = jobs_mod.get_job_manager()
    job_id = "trim-new-clip"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vs.source_path(slug)),
        output_dir=str(out),
        feature="v2_trim",
        trim_output_path=str(trim_path),
    )

    result = mgr.finalize_v2_trim(job_id, "new_clip")
    assert result["mode"] == "new_clip"
    clip_id = result["video_id"]
    assert "::" in clip_id
    meta = vs.resolve_video_id(clip_id)
    assert meta.kind == "clip"
    assert meta.parent_slug == slug
    assert meta.end == 20.0
    clip_dir = vs.clip_dir(slug, meta.clip_slug or "")
    assert (clip_dir / "youtube.mp4").is_file()


def test_finalize_trim_rejects_duplicate(client, monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True, exist_ok=True)

    slug = "vod_dup"
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Dup", kind="original", duration=60.0, size_bytes=100)
    )
    trim_path = tmp_path / "trimmed.mp4"
    trim_path.write_bytes(b"\x00" * 120)
    out = tmp_path / "out_dup"
    out.mkdir()
    (out / "v2_job_context.json").write_text(
        json.dumps({"source_video_id": slug, "keep_spans": [[0, 5]], "trim_output_path": str(trim_path)}),
        encoding="utf-8",
    )

    jobs_mod._manager = JobManager()
    mgr = jobs_mod.get_job_manager()
    job_id = "trim-dup"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vs.source_path(slug)),
        output_dir=str(out),
        feature="v2_trim",
        trim_output_path=str(trim_path),
        trim_finalized=True,
    )

    r = client.post(f"/api/v2/jobs/{job_id}/trim/finalize", json={"mode": "new_clip"})
    assert r.status_code == 400
