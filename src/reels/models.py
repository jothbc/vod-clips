"""Pydantic models for pipeline state and highlights output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

HighlightSource = Literal["heuristic", "vlm", "hybrid"]


class VideoInfo(BaseModel):
    path: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str = ""
    size_bytes: int = 0


class WindowScore(BaseModel):
    start: float
    end: float
    audio_score: float = 0.0
    motion_score: float = 0.0
    scene_score: float = 0.0
    keyword_score: float = 0.0
    heuristic_score: float = 0.0
    vlm_score: float | None = None
    final_score: float = 0.0
    title: str = ""
    reason: str = ""
    source: HighlightSource = "heuristic"
    transcript: str = ""


class Highlight(BaseModel):
    start: float
    end: float
    score: float
    title: str = "Highlight"
    reason: str = ""
    source: HighlightSource = "heuristic"


class HighlightsDocument(BaseModel):
    version: str = "1"
    source_video: str
    preset: str = "default"
    mode: str = "auto"
    vlm_available: bool = True
    warnings: list[str] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)


class PipelineState(BaseModel):
    """Checkpoint state for resumable long VOD analysis."""

    version: str = "1"
    source_video: str
    proxy_path: str = ""
    audio_wav_path: str = ""
    phase: str = "init"
    windows_analyzed: list[str] = Field(default_factory=list)
    vlm_completed: list[str] = Field(default_factory=list)
    heuristic_done: bool = False
    transcribe_done: bool = False
    scenes_done: bool = False

    def window_key(self, start: float, end: float) -> str:
        return f"{start:.2f}-{end:.2f}"


class CaptionWord(BaseModel):
    start: float
    end: float
    word: str


class CaptionSegment(BaseModel):
    index: int
    start: float
    end: float
    text: str
    words: list[CaptionWord] = Field(default_factory=list)


class CaptionsDocument(BaseModel):
    version: str = "1"
    source_video: str
    segments: list[CaptionSegment] = Field(default_factory=list)
    segments_original: list[CaptionSegment] = Field(default_factory=list)
    font_id: str = "montserrat-bold"
    warnings: list[str] = Field(default_factory=list)


EdlKind = Literal["keep", "cut"]


class EdlSpan(BaseModel):
    index: int
    start: float
    end: float
    kind: EdlKind
    source: str = "speech"
    reason: str = ""
    text: str = ""


class EdlDocument(BaseModel):
    version: str = "1"
    source_video: str = ""
    total_duration: float = 0.0
    kept_duration: float = 0.0
    cut_duration: float = 0.0
    llm_available: bool = False
    spans: list[EdlSpan] = Field(default_factory=list)


class PublishItem(BaseModel):
    video_path: str
    source_label: str
    platform: str
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    thumbnail_timestamp: float = 0.0
    thumbnail_path: str = ""


class PublishDocument(BaseModel):
    version: str = "1"
    platform: str = "youtube"
    content_type: str = "game"
    game_name: str = ""
    video_context: str = ""
    channel_info: str = ""
    items: list[PublishItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResolutionPreset(BaseModel):
    id: str
    label: str
    width: int
    height: int


VideoKind = Literal["original", "clip"]


class WebcamRegion(BaseModel):
    """Pixel bbox of the webcam overlay on a desktop-format frame."""

    x1: int
    y1: int
    x2: int
    y2: int
    source_width: int = 0
    source_height: int = 0
    frame_at: float = 0.0


class VideoMetadata(BaseModel):
    """Probe + upload info stored per video slug."""

    version: str = "1"
    slug: str
    title: str = ""
    kind: VideoKind = "original"
    source_filename: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    size_bytes: int = 0
    uploaded_at: str = ""
    parent_slug: str | None = None
    clip_slug: str | None = None
    start: float | None = None
    end: float | None = None
    formats: list[str] = Field(default_factory=list)
    webcam_region: WebcamRegion | None = None


class VideoTranscript(BaseModel):
    version: str = "1"
    video_id: str
    segments: list[dict[str, Any]] = Field(default_factory=list)
    segments_original: list[dict[str, Any]] = Field(default_factory=list)


ClipSourceFeature = Literal["highlight", "captions", "cleanup", "trim", "reformat"]


class ClipMetadata(BaseModel):
    version: str = "1"
    clip_slug: str
    parent_slug: str
    title: str = ""
    start: float = 0.0
    end: float = 0.0
    formats: list[str] = Field(default_factory=list)
    score: float = 0.0
    source_feature: ClipSourceFeature = "highlight"
    webcam_region: WebcamRegion | None = None


class VideoIndex(BaseModel):
    id: str
    title: str
    kind: VideoKind = "original"
    duration: float = 0.0
    width: int = 0
    height: int = 0
    has_transcript: bool = False
    clip_count: int = 0
    parent_id: str | None = None
    format: str | None = None
    start: float | None = None
    end: float | None = None
    formats: list[str] = Field(default_factory=list)
    uploaded_at: str = ""
