"""Twitch VOD download queue with parallel workers."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

import reels.storage as storage
from reels.twitch.download import (
    TwitchDownloadError,
    download_twitch_vod,
    normalize_twitch_vod_url,
    parse_twitch_vod_url,
    parse_yt_dlp_progress_percent,
    require_yt_dlp,
    vod_output_path,
)

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TwitchDownloadRequest(BaseModel):
    url: str


class TwitchDownloadState(BaseModel):
    id: str
    url: str
    video_id: str = ""
    status: str = "queued"
    percent: float = 0.0
    message: str = ""
    path: str = ""
    filename: str = ""
    size_bytes: int = 0
    error: str | None = None
    queue_position: int | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class _QueueItem:
    download_id: str
    url: str


class TwitchDownloadManager:
    """In-memory download queue; dedupes by VOD id and limits concurrent workers."""

    def __init__(self, *, max_concurrent: int = 2, skip_existing: bool = True, concurrent_fragments: int = 32) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._skip_existing = skip_existing
        self._concurrent_fragments = max(1, concurrent_fragments)
        self._downloads: dict[str, TwitchDownloadState] = {}
        self._url_index: dict[str, str] = {}
        self._queue: list[_QueueItem] = []
        self._lock = threading.Lock()
        self._workers: set[str] = set()
        self._cancel_events: dict[str, threading.Event] = {}

    def running_count(self) -> int:
        with self._lock:
            return len(self._workers)

    def _update(self, state: TwitchDownloadState, **kwargs) -> TwitchDownloadState:
        data = state.model_dump()
        data.update(kwargs)
        updated = TwitchDownloadState.model_validate(data)
        self._downloads[state.id] = updated
        return updated

    def get(self, download_id: str) -> TwitchDownloadState | None:
        return self._downloads.get(download_id)

    def list_all(self) -> list[TwitchDownloadState]:
        with self._lock:
            return list(self._downloads.values())

    def start(self, request: TwitchDownloadRequest) -> TwitchDownloadState:
        canonical = normalize_twitch_vod_url(request.url)
        video_id = parse_twitch_vod_url(canonical)

        with self._lock:
            existing_id = self._url_index.get(canonical)
            if existing_id:
                return self._downloads[existing_id]

            dest = vod_output_path(video_id)
            download_id = str(uuid.uuid4())
            now = _utc_now()

            if self._skip_existing and dest.is_file() and dest.stat().st_size >= 1000:
                state = TwitchDownloadState(
                    id=download_id,
                    url=canonical,
                    video_id=video_id,
                    status="completed",
                    percent=100.0,
                    message="Already downloaded",
                    path=str(dest.resolve()),
                    filename=dest.name,
                    size_bytes=dest.stat().st_size,
                    created_at=now,
                    updated_at=now,
                )
                self._downloads[download_id] = state
                self._url_index[canonical] = download_id
                return state

            state = TwitchDownloadState(
                id=download_id,
                url=canonical,
                video_id=video_id,
                status="queued",
                message="Queued",
                created_at=now,
                updated_at=now,
            )
            self._downloads[download_id] = state
            self._url_index[canonical] = download_id
            self._cancel_events[download_id] = threading.Event()
            self._queue.append(_QueueItem(download_id, canonical))
            self._pump_locked()

        return state

    def cancel(self, download_id: str) -> TwitchDownloadState:
        with self._lock:
            state = self._downloads.get(download_id)
            if state is None:
                raise KeyError(f"Download not found: {download_id}")

            event = self._cancel_events.get(download_id)
            if event:
                event.set()

            if state.status == "queued":
                self._queue = [q for q in self._queue if q.download_id != download_id]
                return self._update(
                    state,
                    status="cancelled",
                    message="Cancelled",
                    updated_at=_utc_now(),
                )

            if state.status == "downloading":
                return self._update(
                    state,
                    status="cancelled",
                    message="Cancelling",
                    updated_at=_utc_now(),
                )

            return state

    def _pump_locked(self) -> None:
        while self._queue and len(self._workers) < self._max_concurrent:
            item = self._queue.pop(0)
            state = self._downloads.get(item.download_id)
            if state is None or state.status == "cancelled":
                continue
            self._workers.add(item.download_id)
            thread = threading.Thread(
                target=self._run,
                args=(item.download_id, item.url),
                daemon=True,
            )
            thread.start()

    def _run(self, download_id: str, url: str) -> None:
        cancel_event = self._cancel_events.get(download_id)
        try:
            with self._lock:
                state = self._downloads[download_id]
                if state.status == "cancelled":
                    return
                self._update(
                    state,
                    status="downloading",
                    message="Downloading",
                    percent=0.0,
                    updated_at=_utc_now(),
                )

            video_id = parse_twitch_vod_url(url)
            dest = vod_output_path(video_id)
            yt_dlp = require_yt_dlp()

            def on_progress(line: str) -> None:
                if cancel_event and cancel_event.is_set():
                    return
                with self._lock:
                    current = self._downloads.get(download_id)
                    if current is None:
                        return
                    msg = line[-120:] if line else current.message
                    pct = parse_yt_dlp_progress_percent(line)
                    self._update(
                        current,
                        message=msg,
                        percent=pct if pct is not None else current.percent,
                        updated_at=_utc_now(),
                    )

            download_twitch_vod(
                url,
                dest,
                yt_dlp=yt_dlp,
                concurrent_fragments=self._concurrent_fragments,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

            if cancel_event and cancel_event.is_set():
                dest.unlink(missing_ok=True)
                with self._lock:
                    current = self._downloads[download_id]
                    self._update(
                        current,
                        status="cancelled",
                        message="Cancelled",
                        updated_at=_utc_now(),
                    )
                return

            size = dest.stat().st_size if dest.is_file() else 0
            from reels.video_store import ensure_metadata, twitch_slug

            if dest.is_file():
                ensure_metadata(twitch_slug(video_id), dest, title=f"Twitch VOD {video_id}")
            with self._lock:
                current = self._downloads[download_id]
                self._update(
                    current,
                    status="completed",
                    percent=100.0,
                    message="Completed",
                    path=str(dest.resolve()),
                    filename=dest.name,
                    size_bytes=size,
                    updated_at=_utc_now(),
                )
        except Exception as e:
            with self._lock:
                current = self._downloads.get(download_id)
                if current is None:
                    return
                if cancel_event and cancel_event.is_set():
                    status = "cancelled"
                    message = "Cancelled"
                else:
                    status = "failed"
                    message = str(e)
                self._update(
                    current,
                    status=status,
                    error=None if status == "cancelled" else str(e),
                    message=message,
                    updated_at=_utc_now(),
                )
            if status == "failed":
                logger.error(
                    "Twitch download %s failed (vod=%s url=%s): %s",
                    download_id,
                    parse_twitch_vod_url(url),
                    url,
                    message,
                )
        finally:
            with self._lock:
                self._workers.discard(download_id)
                self._pump_locked()

    def iter_events(
        self,
        download_id: str,
        poll_interval: float = 0.4,
    ):
        """Yield download state snapshots until terminal status."""
        while True:
            state = self.get(download_id)
            if state is None:
                break
            yield state
            if state.status in ("completed", "failed", "cancelled"):
                break
            time.sleep(poll_interval)


_manager: TwitchDownloadManager | None = None


def get_twitch_download_manager() -> TwitchDownloadManager:
    global _manager
    if _manager is None:
        from reels.config import load_config

        cfg = load_config("default")
        td = cfg.twitch_download
        _manager = TwitchDownloadManager(
            max_concurrent=td.max_concurrent,
            skip_existing=td.skip_existing,
            concurrent_fragments=td.concurrent_fragments,
        )
    return _manager


def reset_twitch_download_manager(
    *,
    max_concurrent: int = 2,
    skip_existing: bool = True,
    concurrent_fragments: int = 32,
) -> TwitchDownloadManager:
    """Replace singleton (used by tests)."""
    global _manager
    _manager = TwitchDownloadManager(
        max_concurrent=max_concurrent,
        skip_existing=skip_existing,
        concurrent_fragments=concurrent_fragments,
    )
    return _manager
