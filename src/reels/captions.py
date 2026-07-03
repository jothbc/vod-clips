"""Caption segment building and JSON persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reels.config import CaptionsConfig
from reels.models import CaptionSegment, CaptionWord, CaptionsDocument


def build_caption_segments(
    whisper_segments: list[dict[str, Any]],
    config: CaptionsConfig,
) -> list[CaptionSegment]:
    """Split Whisper output into display lines by gap and word count."""
    words: list[dict[str, Any]] = []
    for seg in whisper_segments:
        seg_words = seg.get("words")
        if seg_words:
            words.extend(seg_words)
        elif seg.get("text"):
            words.append(
                {
                    "start": float(seg.get("start", 0)),
                    "end": float(seg.get("end", 0)),
                    "word": str(seg.get("text", "")).strip(),
                }
            )

    if not words:
        return []

    lines: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [words[0]]

    for prev, word in zip(words, words[1:]):
        gap = float(word.get("start", 0)) - float(prev.get("end", 0))
        if gap > config.word_gap_seconds or len(current) >= config.max_words_per_line:
            lines.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(current)

    segments: list[CaptionSegment] = []
    for index, line_words in enumerate(lines):
        start = float(line_words[0].get("start", 0))
        end = float(line_words[-1].get("end", 0))
        text = " ".join(str(w.get("word", "")).strip() for w in line_words)
        segments.append(
            CaptionSegment(
                index=index,
                start=start,
                end=end,
                text=text,
                words=[
                    CaptionWord(
                        start=float(w.get("start", 0)),
                        end=float(w.get("end", 0)),
                        word=str(w.get("word", "")).strip(),
                    )
                    for w in line_words
                ],
            )
        )
    return segments


def load_captions(path: Path | str) -> CaptionsDocument:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CaptionsDocument.model_validate(data)


def write_captions(path: Path | str, doc: CaptionsDocument) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
