"""Tests for captions/cleanup finalize and create-clip staging."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.jobs import JobManager, JobState, JobStatus
import reels.jobs as jobs_mod
from reels.models import VideoMetadata
import reels.video_store as vs


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod
    import reels.jobs as jobs_mod

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")
    (root / "config" / "cleanup.yaml").write_text("preset: cleanup\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    jobs_mod._manager = None
    yield TestClient(create_app())
    jobs_mod._manager = None


def _seed_vod(slug: str = "vod_stage") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Stage VOD", kind="original", duration=120.0, size_bytes=100)
    )


def test_finalize_captions_new_clip(tmp_path, monkeypatch):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    slug = "vod_cap"
    _seed_vod(slug)

    staged = tmp_path / "captioned.mp4"
    staged.write_bytes(b"\x00" * 80)
    out = tmp_path / "out_cap"
    out.mkdir()
    ctx = {
        "source_video_id": slug,
        "captions_output_path": str(staged),
        "captions_files": {"reels": str(staged)},
        "captions_start": 0.0,
        "captions_end": 30.0,
        "captions_suffix": "with_legend",
        "captions_title_suffix": "legendas",
    }
    (out / "v2_job_context.json").write_text(json.dumps(ctx), encoding="utf-8")

    jobs_mod._manager = JobManager()
    mgr = jobs_mod.get_job_manager()
    job_id = "cap-fin"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vs.source_path(slug)),
        output_dir=str(out),
        feature="v2_captions",
        captions_output_path=str(staged),
    )

    result = mgr.finalize_v2_captions(job_id, "new_clip")
    assert result["mode"] == "new_clip"
    clip_id = result["video_id"]
    assert "::" in clip_id
    meta = vs.resolve_video_id(clip_id)
    assert meta.kind == "clip"
    assert meta.parent_slug == slug
    assert mgr.get_job(job_id).captions_finalized is True


def test_finalize_cleanup_new_vod(tmp_path, monkeypatch):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    slug = "vod_clean"
    _seed_vod(slug)

    staged = tmp_path / "cleaned.mp4"
    staged.write_bytes(b"\x00" * 90)
    out = tmp_path / "out_clean"
    out.mkdir()
    ctx = {
        "source_video_id": slug,
        "cleanup_output_path": str(staged),
        "cleanup_files": {"youtube": str(staged)},
        "cleanup_start": 0.0,
        "cleanup_end": 40.0,
        "cleanup_suffix": "skip_silence",
        "cleanup_title_suffix": "sem silêncios",
    }
    (out / "v2_job_context.json").write_text(json.dumps(ctx), encoding="utf-8")

    monkeypatch.setattr(
        "reels.video_store.probe_video",
        lambda _p: type(
            "I",
            (),
            {
                "duration": 40.0,
                "width": 1280,
                "height": 720,
                "fps": 30.0,
                "codec": "h264",
                "size_bytes": 90,
            },
        )(),
    )

    jobs_mod._manager = JobManager()
    mgr = jobs_mod.get_job_manager()
    job_id = "clean-fin"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vs.source_path(slug)),
        output_dir=str(out),
        feature="v2_cleanup",
        cleanup_output_path=str(staged),
    )

    result = mgr.finalize_v2_cleanup(job_id, "new_vod")
    assert result["mode"] == "new_vod"
    vod_id = result["video_id"]
    assert "::" not in vod_id
    assert vs.source_path(vod_id).is_file()
    assert mgr.get_job(job_id).cleanup_finalized is True


def test_post_create_clip_rejects_clip_source(client):
    _seed_vod("vod_cc")
    vs.save_clip_metadata(
        "vod_cc",
        __import__("reels.models", fromlist=["ClipMetadata"]).ClipMetadata(
            clip_slug="c1",
            parent_slug="vod_cc",
            title="Child",
            start=0.0,
            end=10.0,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id("vod_cc", "c1")
    r = client.post(
        f"/api/v2/videos/{clip_id}/create-clip",
        json={"start": 0, "end": 5, "title": "Nope"},
    )
    assert r.status_code == 400


def test_post_create_clip_starts_job(client, monkeypatch):
    import reels.jobs as jobs_mod

    _seed_vod("vod_create")
    created: dict = {}

    def fake_create(self, req):
        created["feature"] = req.feature
        created["params"] = req.params
        return JobState(
            id="create-1",
            status=JobStatus.QUEUED,
            video_path=req.video_path,
            output_dir=req.output_dir or "",
            feature=req.feature,
        )

    monkeypatch.setattr(jobs_mod.JobManager, "create_job", fake_create)
    r = client.post(
        "/api/v2/videos/vod_create/create-clip",
        json={"start": 1.5, "end": 12.0, "title": "My clip", "burn_captions": True},
    )
    assert r.status_code == 202
    assert created["feature"] == "v2_create_clip"
    assert created["params"]["start"] == 1.5
    assert created["params"]["end"] == 12.0
    assert created["params"]["burn_captions"] is True
    assert created["params"]["title"] == "My clip"


def test_post_create_clip_rejects_short_range(client):
    _seed_vod("vod_short")
    r = client.post(
        "/api/v2/videos/vod_short/create-clip",
        json={"start": 0, "end": 4.9, "title": "Too short"},
    )
    assert r.status_code == 400


def test_load_or_transcribe_does_not_persist_by_default(tmp_path, monkeypatch):
    import reels.storage as storage_mod
    from reels.video_transcript import load_or_transcribe, load_segments

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    slug = "vod_ephemeral"
    _seed_vod(slug)

    work = tmp_path / "job_work"
    work.mkdir()
    segments = [{"start": 0.0, "end": 1.0, "text": "hi"}]

    def fake_transcribe(audio, cfg, warnings=None):
        return segments

    monkeypatch.setattr("reels.video_transcript.probe_video", lambda _p: type("I", (), {"duration": 10, "width": 640, "height": 360})())
    monkeypatch.setattr(
        "reels.video_transcript.generate_proxy",
        lambda *a, **k: (work / "p.mp4", work / "a.wav", None),
    )
    (work / "a.wav").write_bytes(b"RIFF")
    monkeypatch.setattr("reels.video_transcript.transcribe_audio", fake_transcribe)
    monkeypatch.setattr("reels.video_transcript.load_config", lambda _p: object())

    _meta, segs = load_or_transcribe(slug, persist=False, work_dir=work)
    assert segs == segments
    assert load_segments(slug) is None
    assert (work / "segments.json").is_file()

    # Library segments are still readable when present, but not written without persist.
    vs.transcript_dir(slug).mkdir(parents=True, exist_ok=True)
    vs.segments_path(slug).write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "text": "cached"}]), encoding="utf-8"
    )
    _meta, segs2 = load_or_transcribe(slug, persist=False)
    assert segs2[0]["text"] == "cached"
