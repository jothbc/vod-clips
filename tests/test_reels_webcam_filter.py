"""Unit tests for reels webcam filter layout."""

from __future__ import annotations

from reels.export import build_reels_webcam_filter_complex, compute_reels_webcam_layout
from reels.models import WebcamRegion


def test_compute_reels_webcam_layout_splits_canvas():
    region = WebcamRegion(x1=1500, y1=800, x2=1900, y2=1080, source_width=1920, source_height=1080)
    x1, y1, cw, ch, mw, mh, mx, my, out_w, h_cam, h_main = compute_reels_webcam_layout(
        1920, 1080, 608, 1080, region
    )
    assert x1 == 1500
    assert out_w == 608
    assert h_cam + h_main == 1080
    assert h_cam > 0 and h_main > 0


def test_build_reels_webcam_filter_complex_contains_vstack():
    region = WebcamRegion(x1=100, y1=100, x2=400, y2=400, source_width=1920, source_height=1080)
    fc = build_reels_webcam_filter_complex(1920, 1080, 608, 1080, region)
    assert "vstack=inputs=2[vout]" in fc
    assert "crop=300:300:100:100" in fc
    assert "[cam]" in fc and "[main]" in fc
