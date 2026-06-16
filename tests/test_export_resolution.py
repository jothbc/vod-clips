"""Tests for configurable export resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.export import build_crop_filter, build_scale_filter, export_selected
from reels.export_resolution import (
    ExportResolution,
    default_reels_size,
    default_youtube_size,
    reels_presets,
    resolve_reels_size,
    resolve_youtube_size,
    youtube_presets,
)
from reels.config import load_export_profiles
from reels.jobs import JobManager, JobState, JobStatus
from reels.models import Highlight, HighlightsDocument


@pytest.fixture
def client(monkeypatch):
    import reels.jobs as jobs_mod
    import reels.twitch.manager as twitch_mod

    jobs_mod._manager = JobManager()
    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    c = TestClient(create_app())
    yield c
    jobs_mod.get_job_manager()._running = False


def test_default_youtube_size_native():
    assert default_youtube_size(1920, 1080) == (1920, 1080)


def test_default_youtube_size_odd_dims():
    assert default_youtube_size(1919, 1079) == (1918, 1078)


def test_default_reels_size_from_1080p():
    assert default_reels_size(1920, 1080) == (608, 1080)


def test_default_reels_size_from_720p():
    assert default_reels_size(1280, 720) == (404, 720)


def test_youtube_presets_no_upscale_for_720p():
    presets = youtube_presets(1280, 720)
    sizes = {(p.width, p.height) for p in presets}
    assert (3840, 2160) not in sizes
    assert (2560, 1440) not in sizes
    assert (1920, 1080) not in sizes
    assert (1280, 720) in sizes
    assert presets[0].id == "native"


def test_reels_presets_include_source_height():
    presets = reels_presets(1920, 1080)
    assert presets[0].id == "source_height"
    assert (presets[0].width, presets[0].height) == (608, 1080)


def test_resolve_youtube_rejects_upscale():
    with pytest.raises(ValueError, match="cannot exceed source"):
        resolve_youtube_size(ExportResolution(width=1920, height=1080), 1280, 720)


def test_resolve_reels_rejects_wrong_aspect():
    with pytest.raises(ValueError, match="9:16"):
        resolve_reels_size(ExportResolution(width=1920, height=1080), 1920, 1080)


def test_resolve_reels_rejects_tall_upscale():
    with pytest.raises(ValueError, match="cannot exceed source"):
        resolve_reels_size(ExportResolution(width=608, height=1080), 1280, 720)


def test_build_scale_filter_native_no_pad():
    profile = load_export_profiles().youtube.model_copy(update={"width": 1920, "height": 1080})
    vf = build_scale_filter(1920, 1080, profile)
    assert vf == "scale=1920:1080"
    assert "pad=" not in vf


def test_build_scale_filter_downscale_no_upscale():
    profile = load_export_profiles().youtube.model_copy(update={"width": 1920, "height": 1080})
    vf = build_scale_filter(1280, 720, profile)
    assert "scale=1280:720" in vf


def test_build_crop_filter_native_crop_no_scale():
    profile = load_export_profiles().reels.model_copy(update={"width": 608, "height": 1080})
    vf = build_crop_filter(1920, 1080, profile)
    assert vf == "crop=608:1080:656:0"


@patch("reels.export.export_clip")
def test_export_selected_uses_dynamic_profiles(mock_export_clip, tmp_path):
    doc = HighlightsDocument(
        source_video=str(tmp_path / "vod.mp4"),
        highlights=[
            Highlight(start=0, end=10, score=1.0, title="Clip A", reason="", source="heuristic")
        ],
        warnings=[],
    )
    profiles = load_export_profiles()
    config = MagicMock()
    config.clip.max_duration_youtube = 600
    config.clip.max_duration_reels = 90

    export_selected(
        tmp_path / "vod.mp4",
        doc,
        [0],
        tmp_path / "out",
        config,
        profiles=profiles,
        source_width=1920,
        source_height=1080,
        youtube_size=(1280, 720),
        reels_size=(404, 720),
    )

    assert mock_export_clip.call_count == 2
    yt_profile = mock_export_clip.call_args_list[0].args[3]
    reels_profile = mock_export_clip.call_args_list[1].args[3]
    assert (yt_profile.width, yt_profile.height) == (1280, 720)
    assert (reels_profile.width, reels_profile.height) == (404, 720)


@patch("reels.api.app.probe_video")
def test_highlights_includes_resolution_presets(mock_probe, client, tmp_path):
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    highlights = {
        "source_video": str(vod),
        "highlights": [
            {
                "start": 0,
                "end": 5,
                "score": 0.9,
                "title": "Test",
                "reason": "r",
                "source": "heuristic",
            }
        ],
        "warnings": [],
    }
    (out / "highlights.json").write_text(json.dumps(highlights), encoding="utf-8")

    mock_probe.return_value = MagicMock(width=1920, height=1080)

    import reels.jobs as jobs_mod

    job_id = "highlights-res-job"
    jobs_mod.get_job_manager()._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vod),
        output_dir=str(out),
    )
    jobs_mod.get_job_manager()._running = False

    r = client.get(f"/api/jobs/{job_id}/highlights")
    assert r.status_code == 200
    data = r.json()
    assert data["source_width"] == 1920
    assert data["source_height"] == 1080
    assert data["default_youtube"]["width"] == 1920
    assert data["default_reels"]["width"] == 608
    assert len(data["youtube_presets"]) >= 2
    assert len(data["reels_presets"]) >= 1


@patch("reels.jobs.probe_video")
def test_export_api_rejects_invalid_reels_aspect(mock_probe, client, tmp_path):
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()

    mock_probe.return_value = MagicMock(width=1920, height=1080)

    import reels.jobs as jobs_mod

    job_id = "export-invalid-reels"
    jobs_mod.get_job_manager()._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vod),
        output_dir=str(out),
    )
    jobs_mod.get_job_manager()._running = False

    r = client.post(
        f"/api/jobs/{job_id}/export",
        json={
            "highlight_indices": [0],
            "reels_resolution": {"width": 1920, "height": 1080},
        },
    )
    assert r.status_code == 400
    assert "9:16" in r.json()["detail"]
