"""Publish metadata and thumbnail feature."""

from __future__ import annotations

from reels.features import BaseFeature


class PublishFeature(BaseFeature):
    def __init__(self) -> None:
        super().__init__(
            id="publish",
            label="Publish",
            description="Generate PT-BR titles, descriptions, tags, and thumbnails",
        )
