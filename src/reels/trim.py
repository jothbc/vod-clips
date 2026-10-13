"""Manual trim span validation for v2_trim jobs."""

from __future__ import annotations

MIN_SPAN_SECONDS = 0.25


def validate_keep_spans(
    raw: list,
    duration: float,
    *,
    min_span: float = MIN_SPAN_SECONDS,
) -> list[tuple[float, float]]:
    """Normalize and validate keep intervals for ffmpeg export.

    Spans that slightly (or moderately) overshoot the probed duration are
    clamped. UI/metadata duration can disagree with ffprobe; clamping avoids
    false "out of range" failures while still rejecting empty/invalid spans.
    """
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
        if end <= start:
            raise ValueError(f"Span too short: {start}–{end}")
        # Reject spans that start at/after EOF (nothing usable after clamp).
        if start >= duration - 1e-3:
            raise ValueError(f"Span out of range: {start}–{end} (duration {duration})")
        clamped_start = max(0.0, start)
        clamped_end = min(duration, end)
        if clamped_end - clamped_start < min_span:
            raise ValueError(
                f"Span too short after clamp: {start}–{end} (duration {duration})"
            )
        kept.append((clamped_start, clamped_end))

    return kept


# Future (smart cut): stream-copy middle segments + short re-encode at cut edges
# for frame-accurate joins. Out of scope for the fast copy path; revisit if
# keyframe-aligned gaps become a product pain.
def is_simple_chronological_keep(
    spans: list[tuple[float, float]],
    *,
    epsilon: float = MIN_SPAN_SECONDS,
) -> bool:
    """True when spans are a chronological keep-list (removals only, no reorder/dup).

    All must hold: non-empty; playlist order == ascending by start; no overlaps
    beyond ``epsilon``; no consecutive identical ranges.
    """
    if not spans:
        return False
    chronological = sorted(spans, key=lambda s: (s[0], s[1]))
    if list(spans) != chronological:
        return False
    for i in range(len(spans) - 1):
        start, end = spans[i]
        next_start, next_end = spans[i + 1]
        if abs(start - next_start) < 1e-6 and abs(end - next_end) < 1e-6:
            return False
        if end > next_start + epsilon:
            return False
    return True
