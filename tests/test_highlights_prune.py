"""Tests for pruning pending highlights after export."""

from __future__ import annotations

from pathlib import Path

from reels.highlights import load_highlights, prune_exported_highlights, write_highlights
from reels.models import Highlight, HighlightsDocument


def _doc(n: int) -> HighlightsDocument:
    return HighlightsDocument(
        source_video="/tmp/vod.mp4",
        highlights=[
            Highlight(start=float(i * 10), end=float(i * 10 + 5), score=1.0 - i * 0.01, title=f"H{i}")
            for i in range(n)
        ],
    )


def test_prune_exported_keeps_remaining(tmp_path: Path):
    path = tmp_path / "highlights.json"
    write_highlights(path, _doc(4))
    remaining = prune_exported_highlights(path, {0, 2})
    assert remaining is not None
    assert len(remaining.highlights) == 2
    assert remaining.highlights[0].title == "H1"
    assert remaining.highlights[1].title == "H3"
    reloaded = load_highlights(path)
    assert [h.title for h in reloaded.highlights] == ["H1", "H3"]


def test_prune_all_deletes_file(tmp_path: Path):
    path = tmp_path / "highlights.json"
    write_highlights(path, _doc(2))
    remaining = prune_exported_highlights(path, {0, 1})
    assert remaining is None
    assert not path.is_file()


def test_prune_empty_indices_noop(tmp_path: Path):
    path = tmp_path / "highlights.json"
    write_highlights(path, _doc(3))
    remaining = prune_exported_highlights(path, set())
    assert remaining is not None
    assert len(remaining.highlights) == 3
