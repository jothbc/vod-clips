"""Media responses must serve ranges without holding the file open."""

from __future__ import annotations

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reels.api.media_response import MediaFileResponse, media_file_response


def _app(path):
    app = FastAPI()

    @app.get("/v")
    def serve():
        return media_file_response(path, filename="source.mp4")

    return app


def test_full_and_ranged_reads(tmp_path):
    data = bytes(range(256)) * 40
    path = tmp_path / "source.mp4"
    path.write_bytes(data)
    client = TestClient(_app(path))

    full = client.get("/v")
    assert full.status_code == 200
    assert full.content == data
    assert full.headers["accept-ranges"] == "bytes"

    part = client.get("/v", headers={"Range": "bytes=100-299"})
    assert part.status_code == 206
    assert part.content == data[100:300]
    assert part.headers["content-range"] == f"bytes 100-299/{len(data)}"

    tail = client.get("/v", headers={"Range": "bytes=10000-"})
    assert tail.status_code == 206
    assert tail.content == data[10000:]


def test_file_can_be_deleted_mid_stream(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"\x01" * (5 * 1024))
    response = MediaFileResponse(path, media_type="video/mp4", filename="source.mp4")
    response.chunk_size = 1024
    bodies: list[bytes] = []

    async def receive():
        await anyio.sleep(10)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            bodies.append(message["body"])
            if len(bodies) == 1:
                path.unlink()
                assert not path.exists()

    scope = {"type": "http", "method": "GET", "headers": [], "path": "/v"}

    async def main():
        with anyio.fail_after(5):
            await response(scope, receive, send)

    anyio.run(main)
    assert len(bodies) == 1
    assert not path.exists()


def test_stream_stops_on_disconnect(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"\x02" * (64 * 1024))
    response = MediaFileResponse(path, media_type="video/mp4", filename="source.mp4")
    response.chunk_size = 1024
    bodies: list[bytes] = []
    disconnected = anyio.Event()

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            bodies.append(message["body"])
            if len(bodies) == 3:
                disconnected.set()
            await anyio.sleep(0.01)

    scope = {"type": "http", "method": "GET", "headers": [], "path": "/v"}

    async def main():
        with anyio.fail_after(5):
            await response(scope, receive, send)

    anyio.run(main)
    assert len(bodies) < 64
    path.unlink()
    assert not path.exists()
