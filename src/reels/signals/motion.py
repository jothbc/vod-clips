"""Motion score via frame differencing on proxy video."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from reels.config import AppConfig


def compute_motion_scores(
    proxy_path: Path,
    window_seconds: float,
    duration: float,
    config: AppConfig,
    *,
    sample_fps: float = 2.0,
) -> dict[tuple[float, float], float]:
    """Return normalized motion score per analysis window."""
    cap = cv2.VideoCapture(str(proxy_path))
    if not cap.isOpened():
        return {}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    target_h = config.hardware.motion_sample_height
    frame_interval = max(1, int(fps / sample_fps))

    diffs: list[tuple[float, float]] = []
    prev_gray: np.ndarray | None = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval != 0:
            frame_idx += 1
            continue

        h, w = frame.shape[:2]
        scale = target_h / h if h > target_h else 1.0
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), target_h))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        t = frame_idx / fps

        if prev_gray is not None and prev_gray.shape == gray.shape:
            diff = float(np.mean(cv2.absdiff(gray, prev_gray)))
            diffs.append((t, diff))
        prev_gray = gray
        frame_idx += 1

    cap.release()
    if not diffs:
        return {}

    # Aggregate diffs into windows
    hop = window_seconds
    window_scores: dict[tuple[int, int], list[float]] = {}
    for t, d in diffs:
        w_idx = int(t // hop)
        window_scores.setdefault(w_idx, []).append(d)

    raw: dict[tuple[float, float], float] = {}
    for w_idx, vals in window_scores.items():
        start = w_idx * hop
        end = min(start + window_seconds, duration)
        raw[(start, end)] = float(np.mean(vals))

    vals = list(raw.values())
    if not vals:
        return {}
    lo, hi = min(vals), max(vals)
    span = hi - lo if hi - lo > 1e-9 else 1.0
    return {k: (v - lo) / span for k, v in raw.items()}
