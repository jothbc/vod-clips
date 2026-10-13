"""Clean-video EDL: silence math, LLM parsing, keep-span resolution."""

from __future__ import annotations

from reels.cleanup import (
    _parse_cut_indices,
    build_edl,
    filler_cut_intervals,
    keep_spans_after_cuts,
    silence_cut_intervals,
    verify_cuts,
    word_gap_cut_intervals,
)
from reels.config import load_config


class FakeClient:
    """Minimal stand-in for OllamaClient used by verify_cuts tests."""

    def __init__(self, reply: str, available: bool = True):
        self._reply = reply
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def chat_text(self, prompt: str, model: str = "") -> str:
        return self._reply

SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "primeira fala"},
    {"start": 10.0, "end": 12.0, "text": "segunda fala"},
]
DURATION = 20.0


def test_silence_cut_intervals_finds_gap_and_trailing():
    cuts = silence_cut_intervals(
        SEGMENTS, DURATION, min_gap_seconds=0.6, pad_seconds=0.1
    )
    # Gap between 2s..10s and trailing 12s..20s should be cut.
    assert len(cuts) == 2
    (g_start, g_end), (t_start, t_end) = cuts
    assert abs(g_start - 2.1) < 1e-6 and abs(g_end - 9.9) < 1e-6
    assert abs(t_start - 12.1) < 1e-6 and abs(t_end - 20.0) < 1e-6


def test_silence_no_cut_when_gaps_small():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 2.3, "end": 4.0, "text": "b"},
    ]
    cuts = silence_cut_intervals(segs, 4.0, min_gap_seconds=0.6, pad_seconds=0.1)
    assert cuts == []


def test_build_edl_partitions_timeline():
    config = load_config("default")
    doc = build_edl(SEGMENTS, DURATION, config, llm_cut_indices=[], llm_available=False)
    # Full partition covers [0, duration] with no gaps/overlaps.
    assert doc.spans[0].start == 0.0
    assert doc.spans[-1].end == DURATION
    for a, b in zip(doc.spans, doc.spans[1:]):
        assert abs(a.end - b.start) < 1e-6
    assert abs(doc.kept_duration + doc.cut_duration - DURATION) < 1e-3
    assert any(s.kind == "cut" for s in doc.spans)


def test_build_edl_with_llm_cut_marks_segment():
    config = load_config("default")
    doc = build_edl(SEGMENTS, DURATION, config, llm_cut_indices=[1], llm_available=True)
    llm_cuts = [s for s in doc.spans if s.source == "llm"]
    assert llm_cuts, "LLM-flagged segment should appear as a cut span"
    assert doc.llm_available is True


def test_keep_spans_after_cuts_respects_user_toggle():
    config = load_config("default")
    doc = build_edl(SEGMENTS, DURATION, config, llm_cut_indices=[], llm_available=False)
    default_cuts = [s.index for s in doc.spans if s.kind == "cut"]
    kept_default = keep_spans_after_cuts(doc, default_cuts)
    total_default = sum(e - s for s, e in kept_default)

    # Un-cut everything → keep the entire timeline.
    kept_all = keep_spans_after_cuts(doc, [])
    total_all = sum(e - s for s, e in kept_all)
    assert total_all > total_default
    assert abs(total_all - DURATION) < 1e-3


def test_word_gap_cuts_pauses_inside_a_segment():
    # One Whisper segment, but a long pause between the words inside it.
    words = [
        {"start": 0.0, "end": 0.5, "word": "olá"},
        {"start": 3.0, "end": 3.5, "word": "pessoal"},
    ]
    cuts = word_gap_cut_intervals(words, 3.5, min_gap_seconds=0.35, pad_seconds=0.05)
    assert len(cuts) == 1
    cs, ce = cuts[0]
    assert abs(cs - 0.55) < 1e-6 and abs(ce - 2.95) < 1e-6


def test_filler_words_are_cut():
    words = [
        {"start": 0.0, "end": 0.4, "word": "É..."},
        {"start": 0.5, "end": 1.0, "word": "então"},
        {"start": 1.1, "end": 1.4, "word": "ahn"},
    ]
    filler = {"é", "ahn"}
    cuts = filler_cut_intervals(words, filler, pad_seconds=0.05)
    texts = [t for *_n, t in cuts]
    assert "É..." in texts and "ahn" in texts
    assert "então" not in texts


def test_build_edl_word_gaps_more_aggressive_than_segment_gaps():
    config = load_config("default")
    # Single segment spanning a long internal pause, with word timestamps.
    segs = [
        {
            "start": 0.0,
            "end": 6.0,
            "text": "olá pessoal",
            "words": [
                {"start": 0.0, "end": 0.5, "word": "olá"},
                {"start": 5.5, "end": 6.0, "word": "pessoal"},
            ],
        }
    ]
    doc = build_edl(segs, 6.0, config, llm_cut_indices=[], llm_available=False)
    assert any(s.kind == "cut" for s in doc.spans)
    assert doc.cut_duration > 4.0


VERIFY_SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "o frontend é basicamente tudo que"},
    {"start": 2.0, "end": 4.0, "text": "você vê no browser"},
    {"start": 4.0, "end": 6.0, "text": "e o backend é a parte de dados"},
]


def test_verify_cuts_keeps_only_approved_subset():
    config = load_config("default")
    # First pass wanted to cut index 1, but cutting it breaks the sentence,
    # so the verifier approves nothing.
    client = FakeClient('{"cut_indices": []}')
    refined = verify_cuts(client, config, VERIFY_SEGMENTS, [1])
    assert refined == []


def test_verify_cuts_cannot_add_new_indices():
    config = load_config("default")
    # Verifier returns indices not in the original proposal — they are ignored.
    client = FakeClient('{"cut_indices": [0, 2]}')
    refined = verify_cuts(client, config, VERIFY_SEGMENTS, [1])
    assert refined == []


def test_verify_cuts_falls_back_when_unparseable():
    config = load_config("default")
    client = FakeClient("the model rambled without json")
    refined = verify_cuts(client, config, VERIFY_SEGMENTS, [1])
    # Could not parse → keep the original proposal rather than guessing.
    assert refined == [1]


def test_verify_cuts_noop_when_llm_unavailable():
    config = load_config("default")
    client = FakeClient("{}", available=False)
    assert verify_cuts(client, config, VERIFY_SEGMENTS, [1, 2]) == [1, 2]


def test_parse_cut_indices_variants():
    assert _parse_cut_indices('{"cut_indices": [0, 2, 5]}', 10) == [0, 2, 5]
    assert _parse_cut_indices("```json\n{\"cut\": [1]}\n```", 10) == [1]
    assert _parse_cut_indices("[3, 4]", 10) == [3, 4]
    # Out-of-range indices are dropped.
    assert _parse_cut_indices('{"cut_indices": [1, 99]}', 5) == [1]
    assert _parse_cut_indices("not json", 5) == []
