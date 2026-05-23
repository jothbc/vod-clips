"""Tests for highlight merge and dedupe logic."""

from reels.config import AppConfig, HybridWeights, load_config
from reels.highlights import (
    dedupe_highlights,
    merge_auto_highlights,
    merge_hybrid_score,
    overlap_ratio,
)
from reels.models import Highlight, WindowScore


def test_overlap_ratio_full_overlap():
    assert overlap_ratio(0, 10, 0, 10) == 1.0


def test_overlap_ratio_no_overlap():
    assert overlap_ratio(0, 10, 20, 30) == 0.0


def test_overlap_ratio_partial():
    ratio = overlap_ratio(0, 20, 10, 30)
    assert 0 < ratio < 1


def test_merge_hybrid_score():
    config = AppConfig()
    config.analysis.hybrid_weights = HybridWeights(heuristic=0.4, vlm=0.6)
    assert merge_hybrid_score(1.0, 0.0, config) == 0.4
    assert merge_hybrid_score(0.5, 1.0, config) == 0.8
    assert merge_hybrid_score(0.8, None, config) == 0.8


def test_dedupe_keeps_higher_score():
    highlights = [
        Highlight(start=0, end=30, score=0.5, title="low"),
        Highlight(start=5, end=35, score=0.9, title="high"),
    ]
    config = load_config("default")
    result = dedupe_highlights(
        highlights,
        config.clip.dedupe_overlap_ratio,
        config.clip.merge_gap_seconds,
    )
    assert len(result) == 1
    assert result[0].title == "high"


def test_dedupe_keeps_non_overlapping():
    highlights = [
        Highlight(start=0, end=20, score=0.8, title="a"),
        Highlight(start=100, end=120, score=0.7, title="b"),
    ]
    config = load_config("default")
    result = dedupe_highlights(
        highlights,
        config.clip.dedupe_overlap_ratio,
        config.clip.merge_gap_seconds,
    )
    assert len(result) == 2


def test_merge_auto_highlights_hybrid():
    config = load_config("twitch_gaming")
    windows = [
        WindowScore(start=10, end=40, heuristic_score=0.8, final_score=0.8),
        WindowScore(start=100, end=130, heuristic_score=0.6, final_score=0.6),
    ]
    vlm_results = {
        "10.00-40.00": {
            "score": 1.0,
            "title": "Clutch play",
            "reason": "Insane team fight",
        },
    }
    merged = merge_auto_highlights(windows, vlm_results, config, vlm_available=True)
    assert len(merged) >= 1
    top = merged[0]
    assert top.title == "Clutch play"
    assert top.source in ("hybrid", "heuristic", "vlm")
    assert top.start == 7.0  # 10 - pre_pad 3
    assert top.score > 0


def test_merge_auto_respects_max_clips():
    config = load_config("default")
    config.clip.max_clips = 2
    windows = [
        WindowScore(start=i * 60, end=i * 60 + 30, heuristic_score=1.0 - i * 0.1)
        for i in range(10)
    ]
    merged = merge_auto_highlights(windows, {}, config)
    assert len(merged) <= 2
