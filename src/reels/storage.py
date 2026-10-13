"""Project temp storage for uploaded VODs and job outputs."""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import time
import uuid
from pathlib import Path

_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

TEMP_DIR_NAME = "temp"
VODS_SUBDIR = "vods"
OUTPUTS_SUBDIR = "outputs"
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024 * 1024  # 50 GB
# Windows often keeps a video handle open for a moment after the player stops.
_DELETE_ATTEMPTS = 6
_DELETE_BACKOFF_S = 0.25


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
    """Remove a file or directory tree and return the bytes freed.

    Raises OSError when the path is still present after retries. A locked file
    must not be reported as deleted: callers (and the next startup sync) would
    treat the video as gone while the bytes stay on disk.
    """
    path = path.resolve()
    if not path.exists():
        return 0

    freed = _bytes_under(path)
    last_error: BaseException | None = None
    for attempt in range(_DELETE_ATTEMPTS):
        try:
            if path.is_dir() and not path.is_symlink():
                _rmtree(path)
            else:
                _force_writable(path)
                path.unlink()
        except FileNotFoundError:
            return freed
        except OSError as exc:
            last_error = exc
        if not path.exists():
            return freed
        if attempt + 1 < _DELETE_ATTEMPTS:
            time.sleep(_DELETE_BACKOFF_S * (attempt + 1))
    raise OSError(f"Could not delete {path}") from last_error


def _bytes_under(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _force_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _retry_writable(func, target, _exc) -> None:
    _force_writable(Path(target))
    func(target)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry_writable)
        return

    def _onerror(func, target, _exc_info):
        _retry_writable(func, target, None)

    shutil.rmtree(path, onerror=_onerror)


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
