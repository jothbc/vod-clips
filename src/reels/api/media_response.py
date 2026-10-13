"""Range-aware file response that does not hold the media file open."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import anyio
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import FileResponse, PlainTextResponse
from starlette.types import Receive, Scope, Send

try:
    from starlette.responses import MalformedRangeHeader, RangeNotSatisfiable
except ImportError:  # pragma: no cover - older Starlette
    MalformedRangeHeader = RangeNotSatisfiable = None  # type: ignore[assignment,misc]


def _read_chunk(path: str, offset: int, size: int) -> bytes:
    with open(path, "rb") as fh:
        fh.seek(offset)
        return fh.read(size)


class MediaFileResponse(FileResponse):
    """Serve a video file without keeping a handle open between chunks.

    Starlette's FileResponse keeps one handle for the whole response. Browsers
    request ``bytes=0-`` on multi-GB videos and stall the socket once buffered,
    and the server keeps reading after a disconnect. On Windows that open
    handle blocks deleting the file. Opening the file per chunk lets a delete
    go through, and the stream stops on client disconnect or a missing file.
    """

    chunk_size = 1024 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or MalformedRangeHeader is None:
            await super().__call__(scope, receive, send)
            return

        path = str(self.path)
        try:
            stat_result = await anyio.to_thread.run_sync(os.stat, path)
        except FileNotFoundError:
            await PlainTextResponse("Not found", status_code=404)(scope, receive, send)
            return
        if not stat.S_ISREG(stat_result.st_mode):
            await PlainTextResponse("Not found", status_code=404)(scope, receive, send)
            return
        self.set_stat_headers(stat_result)
        file_size = stat_result.st_size

        headers = Headers(scope=scope)
        http_range = headers.get("range")
        http_if_range = headers.get("if-range")
        head_only = scope["method"].upper() == "HEAD"

        start, end = 0, file_size
        status_code = self.status_code
        raw_headers = self.raw_headers
        if http_range is not None and (http_if_range is None or self._should_use_range(http_if_range)):
            try:
                ranges = self._parse_range_header(http_range, file_size)
            except MalformedRangeHeader as exc:
                await PlainTextResponse(exc.content, status_code=400)(scope, receive, send)
                return
            except RangeNotSatisfiable as exc:
                response = PlainTextResponse(
                    status_code=416, headers={"Content-Range": f"bytes */{exc.max_size}"}
                )
                await response(scope, receive, send)
                return
            if len(ranges) != 1:
                await super().__call__(scope, receive, send)
                return
            start, end = ranges[0]
            status_code = 206
            ranged = MutableHeaders(raw=list(self.raw_headers))
            ranged["content-range"] = f"bytes {start}-{end - 1}/{file_size}"
            ranged["content-length"] = str(end - start)
            raw_headers = ranged.raw

        await send({"type": "http.response.start", "status": status_code, "headers": raw_headers})
        if head_only or start >= end:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        async with anyio.create_task_group() as tg:

            async def stream() -> None:
                await self._stream_range(send, path, start, end)
                tg.cancel_scope.cancel()

            async def watch_disconnect() -> None:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        break
                tg.cancel_scope.cancel()

            tg.start_soon(stream)
            tg.start_soon(watch_disconnect)

    async def _stream_range(self, send: Send, path: str, start: int, end: int) -> None:
        pos = start
        while pos < end:
            size = min(self.chunk_size, end - pos)
            try:
                chunk = await anyio.to_thread.run_sync(_read_chunk, path, pos, size)
            except (FileNotFoundError, PermissionError):
                return
            if not chunk:
                return
            pos += len(chunk)
            await send({"type": "http.response.body", "body": chunk, "more_body": pos < end})


def media_file_response(path: Path, *, filename: str) -> MediaFileResponse:
    return MediaFileResponse(path, media_type="video/mp4", filename=filename)
