"""Manual trim span validation for v2_trim jobs."""

from __future__ import annotations

MIN_SPAN_SECONDS = 0.25


def validate_keep_spans(
    raw: list,
    duration: float,
    *,
    min_span: float = MIN_SPAN_SECONDS,
) -> list[tuple[float, float]]:
    """Normalize and validate keep intervals for ffmpeg export."""
    if not raw:
        raise ValueError("keep_spans must not be empty")
    if duration <= 0:
        raise ValueError("Invalid video duration")

    kept: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("Each keep_span must be [start, end]")
        start = float(item[0])
        end = float(item[1])
        if end - start < min_span:
            raise ValueError(f"Span too short: {start}–{end}")
        if start < -0.01 or end > duration + 0.05:
            raise ValueError(f"Span out of range: {start}–{end} (duration {duration})")
        kept.append((max(0.0, start), min(duration, end)))

    return kept
