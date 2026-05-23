"""Save VOD uploaded from browser into project temp/vods."""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from reels.storage import stream_upload_to_temp


async def save_upload_file(upload: UploadFile) -> tuple[Path, str, int]:
    if not upload.filename:
        raise ValueError("Missing filename")
    dest, size = await stream_upload_to_temp(upload, upload.filename)
    return dest, upload.filename, size
