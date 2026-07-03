"""Keyword boost from Whisper transcript segments."""

from __future__ import annotations

import re
from typing import Any

from reels.config import AppConfig


def _compile_patterns(keywords: list[str]) -> list[re.Pattern[str]]:
    patterns = []
    for kw in keywords:
        kw = kw.strip().lower()
        if kw:
            patterns.append(re.compile(re.escape(kw), re.IGNORECASE))
    return patterns


def keyword_scores_from_segments(
    segments: list[dict[str, Any]],
    window_seconds: float,
    duration: float,
    config: AppConfig,
) -> dict[tuple[float, float], float]:
    """Boost windows that contain configured keywords."""
    patterns = _compile_patterns(config.keywords)
    if not patterns:
        return {}

    hop = window_seconds
    n_windows = max(1, int(duration / hop) + 1)
    hits: dict[int, int] = {i: 0 for i in range(n_windows)}

    for seg in segments:
        text = (seg.get("text") or "").lower()
        start = float(seg.get("start", 0))
        if not any(p.search(text) for p in patterns):
            continue
        w_idx = int(start // hop)
        hits[w_idx] = hits.get(w_idx, 0) + 1

    max_hits = max(hits.values()) if hits else 0
    if max_hits == 0:
        return {}

    scores: dict[tuple[float, float], float] = {}
    for w_idx, count in hits.items():
        if count == 0:
            continue
        start = w_idx * hop
        end = min(start + window_seconds, duration)
        scores[(start, end)] = count / max_hits
    return scores
