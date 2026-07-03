"""Pluggable feature registry for the web UI and job dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureInfo:
    id: str
    label: str
    description: str
    enabled: bool = True


@dataclass
class BaseFeature:
    id: str = ""
    label: str = ""
    description: str = ""

    @property
    def enabled(self) -> bool:
        return True


_REGISTRY: dict[str, BaseFeature] = {}


def _register(feature: BaseFeature) -> BaseFeature:
    _REGISTRY[feature.id] = feature
    return feature


def get_feature(feature_id: str) -> BaseFeature:
    feature = _REGISTRY.get(feature_id)
    if feature is None:
        raise KeyError(f"Unknown feature: {feature_id}")
    return feature


def list_feature_info() -> list[dict[str, Any]]:
    return [
        {
            "id": f.id,
            "label": f.label,
            "description": f.description,
            "enabled": f.enabled,
        }
        for f in _REGISTRY.values()
    ]


def _load_features() -> None:
    if _REGISTRY:
        return
    from reels.features.captions import CaptionsFeature
    from reels.features.cleanup import CleanupFeature
    from reels.features.publish import PublishFeature
    from reels.features.reels import ReelsFeature

    for feature in (
        ReelsFeature(),
        CleanupFeature(),
        CaptionsFeature(),
        PublishFeature(),
        BaseFeature(
            id="gallery",
            label="Gallery",
            description="Central media hub for uploads, downloads, and clip selection",
        ),
        BaseFeature(
            id="twitch_download",
            label="Twitch Download",
            description="Download Twitch VODs via yt-dlp",
        ),
        BaseFeature(
            id="reels_library",
            label="Reels Library",
            description="Browse exported clips from previous jobs",
        ),
    ):
        _register(feature)


_load_features()
