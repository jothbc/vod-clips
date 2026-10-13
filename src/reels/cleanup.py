"""Clean-video EDL: silence, word gaps, fillers, and LLM-assisted cuts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from reels.config import AppConfig, prompts_path
from reels.models import EdlDocument, EdlSpan
from reels.vlm.ollama import _fill_prompt

DEFAULT_FILLERS = {
    "é",
    "eh",
    "uh",
    "uhh",
    "ahn",
    "hmm",
    "tipo",
    "né",
    "sabe",
}


def _normalize_word(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def silence_cut_intervals(
    segments: list[dict[str, Any]],
    duration: float,
    min_gap_seconds: float,
    pad_seconds: float,
) -> list[tuple[float, float]]:
    """Return (start, end) intervals to cut for silence between segments."""
    if duration <= 0:
        return []

    sorted_segs = sorted(segments, key=lambda s: float(s.get("start", 0)))
    cuts: list[tuple[float, float]] = []

    if sorted_segs:
        first_start = float(sorted_segs[0].get("start", 0))
        if first_start - pad_seconds > 0 and first_start >= min_gap_seconds:
            cuts.append((0.0, max(0.0, first_start - pad_seconds)))

    for prev, nxt in zip(sorted_segs, sorted_segs[1:]):
        gap_start = float(prev.get("end", 0))
        gap_end = float(nxt.get("start", 0))
        gap = gap_end - gap_start
        if gap >= min_gap_seconds:
            cuts.append((gap_start + pad_seconds, gap_end - pad_seconds))

    if sorted_segs:
        last_end = float(sorted_segs[-1].get("end", 0))
        trailing = duration - last_end
        if trailing >= min_gap_seconds:
            cuts.append((last_end + pad_seconds, duration))

    return [(max(0.0, s), min(duration, e)) for s, e in cuts if e > s]


def word_gap_cut_intervals(
    words: list[dict[str, Any]],
    duration: float,
    min_gap_seconds: float,
    pad_seconds: float,
) -> list[tuple[float, float]]:
    """Cut long pauses between consecutive word timestamps."""
    if len(words) < 2:
        return []
    sorted_words = sorted(words, key=lambda w: float(w.get("start", 0)))
    cuts: list[tuple[float, float]] = []
    for prev, nxt in zip(sorted_words, sorted_words[1:]):
        gap_start = float(prev.get("end", 0))
        gap_end = float(nxt.get("start", 0))
        if gap_end - gap_start >= min_gap_seconds:
            cuts.append((gap_start + pad_seconds, gap_end - pad_seconds))
    return [(max(0.0, s), min(duration, e)) for s, e in cuts if e > s]


def filler_cut_intervals(
    words: list[dict[str, Any]],
    filler_words: set[str],
    pad_seconds: float,
) -> list[tuple[float, float, str]]:
    """Cut individual filler words; returns (start, end, original_text)."""
    cuts: list[tuple[float, float, str]] = []
    normalized_fillers = {_normalize_word(w) for w in filler_words}
    for word in words:
        text = str(word.get("word", ""))
        if _normalize_word(text) in normalized_fillers:
            start = float(word.get("start", 0)) - pad_seconds
            end = float(word.get("end", 0)) + pad_seconds
            cuts.append((max(0.0, start), end, text))
    return cuts


def _merge_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[float, float]] = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e:
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged


def _text_for_range(
    segments: list[dict[str, Any]],
    start: float,
    end: float,
) -> str:
    parts: list[str] = []
    for seg in segments:
        s = float(seg.get("start", 0))
        e = float(seg.get("end", 0))
        if e > start and s < end:
            parts.append(str(seg.get("text", "")))
    return " ".join(parts).strip()


def _collect_cut_regions(
    segments: list[dict[str, Any]],
    duration: float,
    config: AppConfig,
    llm_cut_indices: list[int],
) -> list[tuple[float, float, str, str]]:
    """Return merged cut regions as (start, end, source, reason)."""
    cleanup = config.cleanup
    regions: list[tuple[float, float, str, str]] = []

    for start, end in silence_cut_intervals(
        segments,
        duration,
        cleanup.min_gap_seconds,
        cleanup.pad_seconds,
    ):
        regions.append((start, end, "silence", "silence between speech"))

    all_words: list[dict[str, Any]] = []
    for seg in segments:
        all_words.extend(seg.get("words") or [])

    for start, end in word_gap_cut_intervals(
        all_words,
        duration,
        cleanup.min_gap_seconds,
        cleanup.pad_seconds,
    ):
        regions.append((start, end, "word_gap", "pause within speech"))

    if cleanup.remove_fillers:
        fillers = set(DEFAULT_FILLERS)
        for start, end, text in filler_cut_intervals(
            all_words,
            fillers,
            cleanup.pad_seconds,
        ):
            regions.append((start, end, "filler", f"filler: {text}"))

    for idx in llm_cut_indices:
        if 0 <= idx < len(segments):
            seg = segments[idx]
            regions.append(
                (
                    float(seg.get("start", 0)),
                    float(seg.get("end", 0)),
                    "llm",
                    str(seg.get("text", "")),
                )
            )

    if not regions:
        return []

    merged_times = _merge_intervals([(s, e) for s, e, *_ in regions])
    merged: list[tuple[float, float, str, str]] = []
    for start, end in merged_times:
        sources = [src for s, e, src, _ in regions if s < end and e > start]
        source = "llm" if "llm" in sources else sources[0] if sources else "silence"
        reason = _text_for_range(segments, start, end) or source
        merged.append((start, end, source, reason))
    return merged


def build_edl(
    segments: list[dict[str, Any]],
    duration: float,
    config: AppConfig,
    llm_cut_indices: list[int],
    llm_available: bool,
) -> EdlDocument:
    """Partition the timeline into keep/cut spans covering [0, duration]."""
    cuts = _collect_cut_regions(segments, duration, config, llm_cut_indices)
    spans: list[EdlSpan] = []
    cursor = 0.0
    index = 0

    for cut_start, cut_end, source, reason in cuts:
        if cut_start > cursor:
            spans.append(
                EdlSpan(
                    index=index,
                    start=cursor,
                    end=cut_start,
                    kind="keep",
                    source="speech",
                    reason="",
                    text=_text_for_range(segments, cursor, cut_start),
                )
            )
            index += 1
        if cut_end > cut_start:
            spans.append(
                EdlSpan(
                    index=index,
                    start=cut_start,
                    end=cut_end,
                    kind="cut",
                    source=source,
                    reason=reason,
                    text=_text_for_range(segments, cut_start, cut_end),
                )
            )
            index += 1
        cursor = max(cursor, cut_end)

    if cursor < duration:
        spans.append(
            EdlSpan(
                index=index,
                start=cursor,
                end=duration,
                kind="keep",
                source="speech",
                reason="",
                text=_text_for_range(segments, cursor, duration),
            )
        )

    if not spans:
        spans.append(
            EdlSpan(
                index=0,
                start=0.0,
                end=duration,
                kind="keep",
                source="speech",
                reason="",
                text=_text_for_range(segments, 0, duration),
            )
        )

    kept = sum(s.end - s.start for s in spans if s.kind == "keep")
    cut = sum(s.end - s.start for s in spans if s.kind == "cut")
    return EdlDocument(
        total_duration=duration,
        kept_duration=kept,
        cut_duration=cut,
        llm_available=llm_available,
        spans=spans,
    )


def keep_spans_after_cuts(
    doc: EdlDocument,
    cut_indices: list[int],
) -> list[tuple[float, float]]:
    """Return kept (start, end) intervals after applying selected cut spans."""
    cut_set = set(cut_indices)
    kept: list[tuple[float, float]] = []
    for span in doc.spans:
        if span.kind == "cut" and span.index in cut_set:
            continue
        kept.append((span.start, span.end))
    return _merge_intervals(kept)


def _extract_cut_indices(text: str, max_index: int) -> list[int] | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    candidates: list[int] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for key in ("cut_indices", "cut"):
                if key in parsed and isinstance(parsed[key], list):
                    candidates = [int(x) for x in parsed[key]]
                    break
            else:
                return None
        elif isinstance(parsed, list):
            candidates = [int(x) for x in parsed]
        else:
            return None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return sorted({i for i in candidates if 0 <= i < max_index})


def _parse_cut_indices(text: str, max_index: int) -> list[int]:
    parsed = _extract_cut_indices(text, max_index)
    return parsed if parsed is not None else []


def _format_transcript(segments: list[dict[str, Any]]) -> str:
    lines = []
    for i, seg in enumerate(segments):
        lines.append(f"{i}: {seg.get('text', '')}")
    return "\n".join(lines)


def verify_cuts(
    client: Any,
    config: AppConfig,
    segments: list[dict[str, Any]],
    proposed: list[int],
) -> list[int]:
    """Second-pass LLM review; may only shrink the proposed cut list."""
    if not proposed:
        return []
    if not client.is_available():
        return list(proposed)

    remaining = [
        seg.get("text", "")
        for i, seg in enumerate(segments)
        if i not in proposed
    ]
    result_text = " ".join(remaining).strip()
    template = prompts_path(config, "cleanup_verify.txt").read_text(encoding="utf-8")
    prompt = _fill_prompt(
        template,
        cut_list=", ".join(str(i) for i in proposed),
        result_text=result_text,
        transcript=_format_transcript(segments),
    )
    try:
        reply = client.chat_text(prompt, model=config.cleanup.llm_model)
    except Exception:
        return list(proposed)

    approved = _extract_cut_indices(reply, len(segments))
    if approved is None:
        return list(proposed)
    return [i for i in approved if i in proposed]


def load_edl(path: Path | str) -> EdlDocument:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return EdlDocument.model_validate(data)


def write_edl(path: Path | str, doc: EdlDocument) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc.model_dump_json(indent=2), encoding="utf-8")


def propose_llm_cuts(
    client: Any,
    config: AppConfig,
    segments: list[dict[str, Any]],
) -> list[int]:
    """Ask LLM which transcript segments should be cut."""
    if not config.cleanup.use_llm or not client.is_available():
        return []
    template = prompts_path(config, "cleanup_mistakes.txt").read_text(encoding="utf-8")
    prompt = _fill_prompt(template, transcript=_format_transcript(segments))
    try:
        reply = client.chat_text(prompt, model=config.cleanup.llm_model)
    except Exception:
        return []
    return _parse_cut_indices(reply, len(segments))
