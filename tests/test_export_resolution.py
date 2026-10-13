"""Tests for configurable export resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
from reels.models import Highlight, HighlightsDocument


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
