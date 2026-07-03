"""Project temp storage for uploaded VODs and job outputs."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

TEMP_DIR_NAME = "temp"
VODS_SUBDIR = "vods"
OUTPUTS_SUBDIR = "outputs"
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024 * 1024  # 50 GB


def project_root() -> Path:
    """Reels repo root (parent of config/)."""
    from reels.config import get_config_dir

    return get_config_dir().parent.resolve()


def temp_root() -> Path:
    d = project_root() / TEMP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def temp_vods_dir() -> Path:
    d = temp_root() / VODS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def temp_outputs_dir() -> Path:
    d = temp_root() / OUTPUTS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def job_output_dir(job_id: str) -> Path:
    d = temp_outputs_dir() / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def safe_vod_filename(original: str) -> str:
    base = Path(original).name
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:120]
    if not safe.lower().endswith(".mp4"):
        raise ValueError("Only .mp4 files are supported")
    return safe


def new_vod_path(original_filename: str) -> Path:
    safe = safe_vod_filename(original_filename)
    return temp_vods_dir() / f"{uuid.uuid4().hex[:12]}_{safe}"


def is_under_temp_vods(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(temp_vods_dir())
    except ValueError:
        return False


def is_under_temp_outputs(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(temp_outputs_dir())
    except ValueError:
        return False


async def stream_upload_to_temp(file_obj, filename: str) -> tuple[Path, int]:
    """Write upload stream to temp/vods without loading full file in RAM."""
    dest = new_vod_path(filename)
    total = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file_obj.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"File exceeds maximum upload size ({MAX_UPLOAD_BYTES // (1024**3)} GB)"
                )
            out.write(chunk)
    return dest.resolve(), total


def delete_path(path: Path) -> int:
    """Remove file or directory tree; return bytes freed (estimate)."""
    path = path.resolve()
    if not path.exists():
        return 0

    freed = 0
    if path.is_file():
        freed = path.stat().st_size
        path.unlink()
        return freed

    for p in path.rglob("*"):
        if p.is_file():
            try:
                freed += p.stat().st_size
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)
    return freed


def list_stored_vods() -> list[dict]:
    """List uploaded .mp4 files in temp/vods."""
    items: list[dict] = []
    root = temp_vods_dir()
    for path in root.glob("*.mp4"):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "path": str(path.resolve()),
                "filename": path.name,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    items.sort(key=lambda x: x["modified"], reverse=True)
    return items


def delete_stored_vod(path_str: str) -> dict:
    """Delete one VOD under temp/vods."""
    path = Path(path_str).expanduser().resolve()
    if not is_under_temp_vods(path):
        raise ValueError("Path must be under temp/vods")
    if not path.is_file():
        raise FileNotFoundError(f"VOD not found: {path}")
    freed = delete_path(path)
    return {"deleted": True, "bytes_freed": freed}


def delete_reel_job_output(job_id: str) -> dict:
    """Remove one exported session folder under temp/outputs."""
    if not _JOB_ID_RE.match(job_id) or ".." in job_id:
        raise ValueError("Invalid job id")
    job_dir = temp_outputs_dir() / job_id
    if not job_dir.is_dir():
        raise FileNotFoundError(f"Job output not found: {job_id}")
    freed = delete_path(job_dir)
    return {"deleted": True, "bytes_freed": freed}


def cleanup_job_files(video_path: str | None, output_dir: str | None) -> dict:
    """Delete uploaded VOD (if in temp) and job output folder (if in temp)."""
    result = {"vod_deleted": False, "output_deleted": False, "bytes_freed": 0}

    if video_path:
        vp = Path(video_path)
        if is_under_temp_vods(vp):
            result["bytes_freed"] += delete_path(vp)
            result["vod_deleted"] = True

    if output_dir:
        od = Path(output_dir)
        if is_under_temp_outputs(od):
            result["bytes_freed"] += delete_path(od)
            result["output_deleted"] = True

    return result
