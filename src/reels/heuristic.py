"""Gaming heuristic ranking without VLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reels.chunking import build_windows, detect_scenes, scene_density_scores
from reels.config import AppConfig
from reels.models import Highlight, WindowScore
from reels.signals.audio_peaks import apply_silence_penalty, compute_audio_scores
from reels.signals.keywords import keyword_scores_from_segments
from reels.signals.motion import compute_motion_scores


def rank_heuristic_windows(
    audio_wav: Path,
    proxy_path: Path,
    duration: float,
    config: AppConfig,
    segments: list[dict[str, Any]] | None = None,
    *,
    scenes: list[tuple[float, float]] | None = None,
) -> list[WindowScore]:
    """Combine audio, motion, scene density, keywords into ranked windows."""
    ws = config.analysis.window_seconds
    weights = config.analysis.heuristic_weights

    audio = compute_audio_scores(audio_wav, ws, duration)
    motion = compute_motion_scores(proxy_path, ws, duration, config)

    if scenes is None:
        try:
            scenes = detect_scenes(proxy_path)
        except Exception:
            scenes = []
    scene = scene_density_scores(scenes, ws, duration)
    keywords = keyword_scores_from_segments(segments or [], ws, duration, config)

    audio = apply_silence_penalty(
        audio,
        motion,
        config.analysis.silence_rms_threshold,
        config.analysis.silence_motion_threshold,
    )

    windows = build_windows(duration, ws)
    results: list[WindowScore] = []

    for start, end in windows:
        key = (start, end)
        # nearest key fallback
        a = _lookup(audio, start, end, ws)
        m = _lookup(motion, start, end, ws)
        s = _lookup(scene, start, end, ws)
        k = _lookup(keywords, start, end, ws)

        h_score = (
            weights.audio * a
            + weights.motion * m
            + weights.scene_density * s
            + weights.keywords * k
        )
        results.append(
            WindowScore(
                start=start,
                end=end,
                audio_score=a,
                motion_score=m,
                scene_score=s,
                keyword_score=k,
                heuristic_score=h_score,
                final_score=h_score,
                source="heuristic",
            )
        )

    results.sort(key=lambda w: w.heuristic_score, reverse=True)
    return results


def _lookup(
    scores: dict[tuple[float, float], float],
    start: float,
    end: float,
    window_seconds: float,
) -> float:
    if (start, end) in scores:
        return scores[(start, end)]
    # align to grid
    key = (int(start // window_seconds) * window_seconds, end)
    for (s, e), v in scores.items():
        if abs(s - start) < 0.5 and abs(e - end) < window_seconds:
            return v
    return 0.0


def windows_to_highlights(
    windows: list[WindowScore],
    config: AppConfig,
) -> list[Highlight]:
    """Take top windows and convert to clip ranges with padding."""
    max_clips = config.clip.max_clips
    pre = config.clip.pre_pad_seconds
    post = config.clip.post_pad_seconds
    min_d = config.clip.min_duration
    max_d = config.clip.max_duration_reels

    highlights: list[Highlight] = []
    for w in windows[: max_clips * 3]:
        start = max(0.0, w.start - pre)
        end = w.end + post
        if end - start < min_d:
            end = start + min_d
        if end - start > max_d:
            end = start + max_d
        highlights.append(
            Highlight(
                start=start,
                end=end,
                score=w.final_score,
                title=w.title or f"Highlight @ {int(w.start)}s",
                reason=w.reason or "High intensity gaming moment",
                source=w.source,
            )
        )
    return highlights
