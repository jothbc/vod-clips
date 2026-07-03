"""Merge heuristic + VLM highlights, dedupe, write highlights.json."""

from __future__ import annotations

import json
from pathlib import Path

from reels.config import AppConfig
from reels.models import Highlight, HighlightsDocument, WindowScore


def overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    if overlap <= 0:
        return 0.0
    span_a = a_end - a_start
    span_b = b_end - b_start
    return overlap / min(span_a, span_b) if min(span_a, span_b) > 0 else 0.0


def dedupe_highlights(
    highlights: list[Highlight],
    overlap_ratio_threshold: float,
    merge_gap_seconds: float,
) -> list[Highlight]:
    """Remove overlapping highlights, keeping highest score."""
    if not highlights:
        return []

    sorted_h = sorted(highlights, key=lambda h: h.score, reverse=True)
    kept: list[Highlight] = []

    for candidate in sorted_h:
        dominated = False
        for existing in kept:
            ratio = overlap_ratio(
                candidate.start,
                candidate.end,
                existing.start,
                existing.end,
            )
            gap = min(
                abs(candidate.start - existing.end),
                abs(existing.start - candidate.end),
            )
            if ratio >= overlap_ratio_threshold or gap <= merge_gap_seconds:
                dominated = True
                break
        if not dominated:
            kept.append(candidate)

    return sorted(kept, key=lambda h: h.score, reverse=True)


def merge_hybrid_score(
    heuristic: float,
    vlm: float | None,
    config: AppConfig,
) -> float:
    hw = config.analysis.hybrid_weights
    if vlm is None:
        return heuristic
    return hw.heuristic * heuristic + hw.vlm * vlm


def merge_auto_highlights(
    heuristic_windows: list[WindowScore],
    vlm_results: dict[str, dict],
    config: AppConfig,
    *,
    vlm_available: bool = True,
) -> list[Highlight]:
    """Merge heuristic and VLM into hybrid highlights."""
    pre = config.clip.pre_pad_seconds
    post = config.clip.post_pad_seconds
    min_d = config.clip.min_duration
    max_d = config.clip.max_duration_reels

    by_key: dict[str, WindowScore] = {}
    for w in heuristic_windows:
        by_key[_key(w.start, w.end)] = w

    merged: list[Highlight] = []
    for w in heuristic_windows:
        key = _key(w.start, w.end)
        vlm_data = vlm_results.get(key)
        vlm_score = float(vlm_data["score"]) if vlm_data else None
        h_score = w.heuristic_score
        final = merge_hybrid_score(h_score, vlm_score, config)

        if vlm_data:
            title = str(vlm_data.get("title", w.title))
            reason = str(vlm_data.get("reason", w.reason))
            source = "hybrid" if vlm_available else "heuristic"
        else:
            title = w.title or f"Highlight @ {int(w.start)}s"
            reason = w.reason or "High intensity gaming moment"
            source = "heuristic"

        start = max(0.0, w.start - pre)
        end = w.end + post
        if end - start < min_d:
            end = start + min_d
        if end - start > max_d:
            end = start + max_d

        merged.append(
            Highlight(
                start=start,
                end=end,
                score=final,
                title=title,
                reason=reason,
                source=source,  # type: ignore[arg-type]
            )
        )

    # Add VLM-only windows not in heuristic top set
    for key, vlm_data in vlm_results.items():
        if key in by_key:
            continue
        parts = key.split("-")
        if len(parts) != 2:
            continue
        start, end = float(parts[0]), float(parts[1])
        start_p = max(0.0, start - pre)
        end_p = end + post
        merged.append(
            Highlight(
                start=start_p,
                end=end_p,
                score=float(vlm_data.get("score", 0.5)),
                title=str(vlm_data.get("title", "VLM Highlight")),
                reason=str(vlm_data.get("reason", "")),
                source="vlm",
            )
        )

    deduped = dedupe_highlights(
        merged,
        config.clip.dedupe_overlap_ratio,
        config.clip.merge_gap_seconds,
    )
    return deduped[: config.clip.max_clips]


def gaming_highlights_from_windows(
    windows: list[WindowScore],
    config: AppConfig,
) -> list[Highlight]:
    from reels.heuristic import windows_to_highlights

    top = windows[: config.clip.max_clips * 2]
    raw = windows_to_highlights(top, config)
    return dedupe_highlights(
        raw,
        config.clip.dedupe_overlap_ratio,
        config.clip.merge_gap_seconds,
    )[: config.clip.max_clips]


def write_highlights(path: Path, doc: HighlightsDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc.model_dump(), indent=2),
        encoding="utf-8",
    )


def load_highlights(path: Path) -> HighlightsDocument:
    data = json.loads(path.read_text(encoding="utf-8"))
    return HighlightsDocument.model_validate(data)


def _key(start: float, end: float) -> str:
    return f"{start:.2f}-{end:.2f}"
