"""Heuristic signal extractors for gaming highlights."""

from reels.signals.audio_peaks import compute_audio_scores
from reels.signals.keywords import keyword_scores_from_segments
from reels.signals.motion import compute_motion_scores

__all__ = [
    "compute_audio_scores",
    "compute_motion_scores",
    "keyword_scores_from_segments",
]
