"""Scene detection and analysis window generation."""

from __future__ import annotations

from pathlib import Path

from scenedetect import ContentDetector, SceneManager, open_video

from reels.config import AppConfig


def detect_scenes(proxy_path: Path, threshold: float = 27.0) -> list[tuple[float, float]]:
    """Return list of (start, end) scene boundaries."""
    video = open_video(str(proxy_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold))
    manager.detect_scenes(video)
    scene_list = manager.get_scene_list()
    return [
        (s.get_seconds(), e.get_seconds())
        for s, e in scene_list
    ]


def scene_density_scores(
    scenes: list[tuple[float, float]],
    window_seconds: float,
    duration: float,
) -> dict[tuple[float, float], float]:
    """Score windows by scene cut density (transitions, death screens)."""
    if not scenes:
        return {}

    cut_times = [s[0] for s in scenes[1:]]  # cuts at scene starts
    hop = window_seconds
    n_windows = max(1, int(duration / hop) + 1)
    counts: dict[int, int] = {i: 0 for i in range(n_windows)}

    for t in cut_times:
        w_idx = int(t // hop)
        if 0 <= w_idx < n_windows:
            counts[w_idx] = counts.get(w_idx, 0) + 1

    max_c = max(counts.values()) if counts else 0
    if max_c == 0:
        return {}

    return {
        (i * hop, min((i + 1) * hop, duration)): counts[i] / max_c
        for i in range(n_windows)
        if counts.get(i, 0) > 0
    }


def build_windows(duration: float, window_seconds: float) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        end = min(start + window_seconds, duration)
        windows.append((start, end))
        start += window_seconds
    return windows


def prefilter_windows(
    window_scores: list[tuple[float, float, float]],
    top_percent: float,
    max_windows: int,
) -> list[tuple[float, float]]:
    """Select top N% windows by heuristic score for VLM."""
    if not window_scores:
        return []
    sorted_ws = sorted(window_scores, key=lambda x: x[2], reverse=True)
    n = max(1, int(len(sorted_ws) * top_percent / 100.0))
    n = min(n, max_windows, len(sorted_ws))
    selected = sorted_ws[:n]
    return [(s, e) for s, e, _ in selected]
