"""Tests for clip-scoped transcript slicing."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import ClipMetadata, VideoMetadata
from reels.video_transcript import load_or_transcribe, slice_segments_for_window
import reels.video_store as vs


def test_slice_segments_for_window_clips_times():
    segments = [
        {"start": 0.0, "end": 10.0, "text": "before"},
        {"start": 100.0, "end": 110.0, "text": "inside"},
        {"start": 105.0, "end": 115.0, "text": "overlap"},
        {"start": 120.0, "end": 130.0, "text": "after"},
    ]
    sliced = slice_segments_for_window(segments, 100.0, 125.0)
    assert len(sliced) == 3
    assert sliced[0]["text"] == "inside"
    assert sliced[0]["start"] == 100.0
    assert sliced[1]["text"] == "overlap"
    assert sliced[1]["start"] == 105.0
    assert sliced[1]["end"] == 115.0
    assert sliced[2]["text"] == "after"
    assert sliced[2]["start"] == 120.0
    assert sliced[2]["end"] == 125.0


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


def _seed_vod_with_transcript(slug: str = "vod_t") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title="Test VOD", kind="original", duration=200.0, size_bytes=100)
    )
    segments = [
        {"start": 0.0, "end": 10.0, "text": "intro"},
        {"start": 100.0, "end": 110.0, "text": "clip line"},
        {"start": 150.0, "end": 160.0, "text": "later"},
    ]
    vs.transcript_dir(slug).mkdir(parents=True)
    vs.segments_path(slug).write_text(json.dumps(segments), encoding="utf-8")


def test_get_transcript_clip_returns_window_only(client):
    _seed_vod_with_transcript("vod_t")
    vs.save_clip_metadata(
        "vod_t",
        ClipMetadata(
            clip_slug="clip_04",
            parent_slug="vod_t",
            title="My Clip",
            start=100.0,
            end=125.0,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id("vod_t", "clip_04")
    r = client.get(f"/api/v2/videos/{clip_id}/transcript")
    assert r.status_code == 200
    data = r.json()
    assert data["video_id"] == clip_id
    assert data["window"] == {"start": 100.0, "end": 125.0}
    assert len(data["segments"]) == 1
    assert data["segments"][0]["text"] == "clip line"
    assert data["segments"][0]["start"] == 100.0


def test_put_transcript_clip_merges_to_parent(client):
    _seed_vod_with_transcript("vod_t")
    vs.save_clip_metadata(
        "vod_t",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="vod_t",
            title="Clip",
            start=100.0,
            end=125.0,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id("vod_t", "clip_00")
    r = client.put(
        f"/api/v2/videos/{clip_id}/transcript",
        json={"segments": [{"start": 100.0, "end": 110.0, "text": "edited line"}]},
    )
    assert r.status_code == 200
    parent = json.loads(vs.segments_path("vod_t").read_text(encoding="utf-8"))
    assert parent[1]["text"] == "edited line"
    vod = client.get("/api/v2/videos/vod_t/transcript")
    assert vod.status_code == 200
    assert vod.json()["segments"][1]["text"] == "edited line"
    clip = client.get(f"/api/v2/videos/{clip_id}/transcript")
    assert clip.json()["segments"][0]["text"] == "edited line"


def test_load_or_transcribe_force_reruns(monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    _seed_vod_with_transcript("vod_force")
    calls = {"n": 0}

    def fake_transcribe(*_a, **_k):
        calls["n"] += 1
        return [{"start": 0.0, "end": 1.0, "text": "new"}]

    monkeypatch.setattr("reels.video_transcript.transcribe_audio", fake_transcribe)
    monkeypatch.setattr(
        "reels.video_transcript.generate_proxy",
        lambda *a, **k: (None, vs.audio_path("vod_force"), None),
    )
    monkeypatch.setattr(
        "reels.video_transcript.probe_video",
        lambda _p: type("I", (), {"duration": 10.0, "width": 1, "height": 1})(),
    )
    vs.audio_path("vod_force").parent.mkdir(parents=True, exist_ok=True)
    vs.audio_path("vod_force").write_bytes(b"\x00")

    _meta, segs = load_or_transcribe("vod_force")
    assert segs[0]["text"] == "intro"
    assert calls["n"] == 0

    _meta, segs = load_or_transcribe("vod_force", force=True)
    assert segs[0]["text"] == "new"
    assert calls["n"] == 1
