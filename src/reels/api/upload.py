"""Save VOD uploaded from browser into temp/video/{slug}/."""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from reels.models import VideoMetadata
from reels.video_store import stream_upload_to_video


async def save_upload_file(upload: UploadFile) -> tuple[VideoMetadata, str, int]:
    if not upload.filename:
        raise ValueError("Missing filename")
    meta, size = await stream_upload_to_video(upload, upload.filename)
    return meta, upload.filename, size
