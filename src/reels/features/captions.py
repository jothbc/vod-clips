"""Captions and burn-in feature."""

from __future__ import annotations

from reels.features import BaseFeature


class CaptionsFeature(BaseFeature):
    def __init__(self) -> None:
        super().__init__(
            id="captions",
            label="Captions",
            description="Generate, edit, and burn karaoke captions into video",
        )
