"""Pydantic models for pipeline state and highlights output."""

from __future__ import annotations

from typing import Literal

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
