"""Configurable export resolution presets and validation."""

from __future__ import annotations

from reels.models import ResolutionPreset


class ExportResolution:
    """Width/height pair for export API requests."""

    def __init__(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def default_youtube_size(source_width: int, source_height: int) -> tuple[int, int]:
    return (_even(source_width), _even(source_height))


def default_reels_size(source_width: int, source_height: int) -> tuple[int, int]:
    height = _even(source_height)
    width = _even((height * 9 + 15) // 16)
    return (width, height)


def _is_9_16(width: int, height: int) -> bool:
    if height <= 0:
        return False
    ratio = width / height
    return abs(ratio - 9 / 16) < 0.02


def youtube_presets(source_width: int, source_height: int) -> list[ResolutionPreset]:
    native_w, native_h = default_youtube_size(source_width, source_height)
    presets: list[ResolutionPreset] = [
        ResolutionPreset(id="native", label="Native", width=native_w, height=native_h),
    ]
    candidates = [
        ("4k", "4K", 3840, 2160),
        ("1440p", "1440p", 2560, 1440),
        ("1080p", "1080p", 1920, 1080),
        ("720p", "720p", 1280, 720),
    ]
    for pid, label, w, h in candidates:
        if w <= source_width and h <= source_height and (w, h) != (native_w, native_h):
            presets.append(ResolutionPreset(id=pid, label=label, width=w, height=h))
    return presets


def reels_presets(source_width: int, source_height: int) -> list[ResolutionPreset]:
    w, h = default_reels_size(source_width, source_height)
    presets = [
        ResolutionPreset(id="source_height", label="Source height", width=w, height=h),
    ]
    for pid, label, tw, th in [
        ("1080", "1080p vertical", 608, 1080),
        ("720", "720p vertical", 404, 720),
    ]:
        if th <= source_height and tw <= source_width and (tw, th) != (w, h):
            presets.append(ResolutionPreset(id=pid, label=label, width=tw, height=th))
    return presets


def resolve_youtube_size(
    resolution: ExportResolution,
    source_width: int,
    source_height: int,
) -> tuple[int, int]:
    w, h = _even(resolution.width), _even(resolution.height)
    if w > source_width or h > source_height:
        raise ValueError("Target resolution cannot exceed source dimensions")
    return (w, h)


def resolve_reels_size(
    resolution: ExportResolution,
    source_width: int,
    source_height: int,
) -> tuple[int, int]:
    w, h = _even(resolution.width), _even(resolution.height)
    if not _is_9_16(w, h):
        raise ValueError("Reels resolution must be 9:16 aspect ratio")
    if h > source_height or w > source_width:
        raise ValueError("Target resolution cannot exceed source dimensions")
    return (w, h)
