"""Clean-video editing feature."""

from __future__ import annotations

from reels.features import BaseFeature


class CleanupFeature(BaseFeature):
    def __init__(self) -> None:
        super().__init__(
            id="cleanup",
            label="Clean Video",
            description="Remove silence, pauses, and filler with an editable EDL",
        )
