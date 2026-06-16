"""Captions feature tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.caption_fonts import list_caption_fonts
from reels.captions import build_caption_segments, load_captions, write_captions
from reels.captions_render import write_ass_file
from reels.config import CaptionsConfig, load_config
from reels.jobs import JobManager, JobState, JobStatus
from reels.models import CaptionSegment, CaptionWord, CaptionsDocument


@pytest.fixture
def client(monkeypatch):
    import reels.jobs as jobs_mod
    import reels.twitch.manager as twitch_mod

    jobs_mod._manager = JobManager()
    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    c = TestClient(create_app())
    yield c
    jobs_mod.get_job_manager()._running = False


def test_build_caption_segments_splits_on_long_gap():
    whisper = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "hello world",
            "words": [
                {"start": 0.0, "end": 0.4, "word": "hello"},
                {"start": 0.4, "end": 0.8, "word": "world"},
                {"start": 2.0, "end": 2.4, "word": "again"},
                {"start": 2.4, "end": 2.8, "word": "now"},
            ],
        }
    ]
    cfg = CaptionsConfig(max_words_per_line=4, word_gap_seconds=0.35)
    segments = build_caption_segments(whisper, cfg)
    assert len(segments) == 2
    assert segments[0].text == "hello world"
    assert segments[1].text == "again now"


def test_build_caption_segments_respects_max_words():
    whisper = [
        {
            "start": 0.0,
            "end": 3.0,
            "words": [
                {"start": 0.0, "end": 0.5, "word": "one"},
                {"start": 0.5, "end": 1.0, "word": "two"},
                {"start": 1.0, "end": 1.5, "word": "three"},
                {"start": 1.5, "end": 2.0, "word": "four"},
                {"start": 2.0, "end": 2.5, "word": "five"},
            ],
        }
    ]
    segments = build_caption_segments(whisper, CaptionsConfig(max_words_per_line= 4))
    assert len(segments) == 2
    assert segments[0].text == "one two three four"
    assert segments[1].text == "five"


def test_write_ass_file_contains_karaoke_tags(tmp_path):
    doc = CaptionsDocument(
        source_video="/tmp/v.mp4",
        segments=[
            CaptionSegment(
                index=0,
                start=1.0,
                end=2.0,
                text="Hello world",
                words=[
                    CaptionWord(start=1.0, end=1.5, word="Hello"),
                    CaptionWord(start=1.5, end=2.0, word="world"),
                ],
            )
        ],
    )
    ass_path = tmp_path / "test.ass"
    write_ass_file(
        doc,
        ass_path,
        video_width=1080,
        video_height=1920,
        font_family="Montserrat",
        config=CaptionsConfig(),
    )
    content = ass_path.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "PlayResX: 1080" in content
    assert "\\k" in content
    assert "Hello" in content
    assert "Dialogue:" in content


def test_caption_fonts_api_lists_bundled_fonts(client):
    r = client.get("/api/captions/fonts")
    assert r.status_code == 200
    fonts = r.json()["fonts"]
    assert len(fonts) >= 1
    assert any(f["id"] == "montserrat-bold" for f in fonts)


def test_put_and_get_captions_persist_edits(client, tmp_path):
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x" * 100)
    out = tmp_path / "out"
    out.mkdir()
    doc = CaptionsDocument(
        source_video=str(vod),
        segments=[
            CaptionSegment(
                index=0,
                start=0,
                end=1,
                text="original",
                words=[CaptionWord(start=0, end=1, word="original")],
            )
        ],
        segments_original=[
            CaptionSegment(
                index=0,
                start=0,
                end=1,
                text="original",
                words=[CaptionWord(start=0, end=1, word="original")],
            )
        ],
    )
    write_captions(out / "captions.json", doc)

    import reels.jobs as jobs_mod

    job_id = "captions-edit-job"
    jobs_mod.get_job_manager()._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vod),
        output_dir=str(out),
        feature="captions",
    )
    jobs_mod.get_job_manager()._running = False

    edited = {
        "segments": [
            {
                "index": 0,
                "start": 0,
                "end": 1,
                "text": "edited text",
                "words": [{"start": 0, "end": 1, "word": "edited"}],
            }
        ],
        "font_id": "anton",
    }
    put = client.put(f"/api/jobs/{job_id}/captions", json=edited)
    assert put.status_code == 200
    assert put.json()["segments"][0]["text"] == "edited text"
    assert put.json()["font_id"] == "anton"

    get = client.get(f"/api/jobs/{job_id}/captions")
    assert get.status_code == 200
    assert get.json()["segments"][0]["text"] == "edited text"

    saved = load_captions(out / "captions.json")
    assert saved.segments[0].text == "edited text"
    assert saved.font_id == "anton"


@patch("reels.jobs.probe_video")
@patch("reels.captions_render.render_captioned_video")
def test_render_captions_job_completes(mock_render, mock_probe, client, tmp_path):
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x" * 100)
    out = tmp_path / "out"
    out.mkdir()
    write_captions(
        out / "captions.json",
        CaptionsDocument(
            source_video=str(vod),
            segments=[
                CaptionSegment(index=0, start=0, end=1, text="hi", words=[])
            ],
        ),
    )
    (out / "captioned.mp4").write_bytes(b"\x00" * 5000)

    mock_probe.return_value = MagicMock(width=1920, height=1080)

    import reels.jobs as jobs_mod

    job_id = "captions-render-job"
    mgr = jobs_mod.get_job_manager()
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vod),
        output_dir=str(out),
        feature="captions",
        preset="default",
    )
    mgr._running = False

    def fake_render(*_a, **_k):
        (out / "captioned.mp4").write_bytes(b"\x00" * 5000)

    mock_render.side_effect = fake_render

    r = client.post(
        f"/api/jobs/{job_id}/render-captions",
        json={"font_id": "montserrat-bold", "use_nvenc": False},
    )
    assert r.status_code == 200

    import time

    deadline = time.time() + 5
    while time.time() < deadline:
        state = mgr.get_job(job_id)
        if state and state.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            break
        time.sleep(0.05)
    final = mgr.get_job(job_id)
    assert final.status == JobStatus.COMPLETED
    assert final.phase == "done"
    assert final.percent == 100.0
    mock_render.assert_called_once()


def test_list_caption_fonts_returns_catalog_entries():
    fonts = list_caption_fonts()
    assert fonts
    assert all("id" in f and "label" in f for f in fonts)
