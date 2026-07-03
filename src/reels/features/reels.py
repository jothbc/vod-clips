"""Highlight analysis and export feature."""

from __future__ import annotations

from reels.features import BaseFeature


class ReelsFeature(BaseFeature):
    def __init__(self) -> None:
        super().__init__(
            id="reels",
            label="Generate Reels",
            description="Find highlights with Whisper + heuristics and export clips",
        )
