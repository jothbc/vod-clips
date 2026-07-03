"""API response schemas."""

from __future__ import annotations

from pydantic import BaseModel

from reels.jobs import CreateJobRequest, JobState


class CreateJobResponse(BaseModel):
    job_id: str


class ClipItem(BaseModel):
    index: int
    title: str
    score: float
    start: float
    end: float
    source: str
    youtube_url: str | None = None
    reels_url: str | None = None
    youtube_filename: str | None = None
    reels_filename: str | None = None


class ClipsResponse(BaseModel):
    job_id: str
    output_dir: str
    clips: list[ClipItem]


class HealthResponse(BaseModel):
    ffmpeg: bool
    ollama: bool
    ollama_host: str


class UploadResponse(BaseModel):
    path: str
    filename: str
    size_bytes: int
    video_id: str = ""


class CleanupResponse(BaseModel):
    vod_deleted: bool
    output_deleted: bool
    bytes_freed: int
    already_cleaned: bool = False
