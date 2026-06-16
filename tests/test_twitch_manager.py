"""Twitch download queue: parallel workers, dedupe, skip_existing, cancel."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from reels.twitch.download import vod_output_path
from reels.twitch.manager import TwitchDownloadManager, TwitchDownloadRequest


@pytest.fixture
def manager(monkeypatch, tmp_path):
    import reels.storage as storage_mod
    import reels.twitch.download as dl_mod

    vods = tmp_path / "vods"
    vods.mkdir()
    monkeypatch.setattr(storage_mod, "temp_vods_dir", lambda: vods)
    monkeypatch.setattr(dl_mod, "temp_vods_dir", lambda: vods)
    return TwitchDownloadManager(max_concurrent=2, skip_existing=True)


def test_dedupe_returns_same_download(manager):
    url = "https://www.twitch.tv/videos/1111111111"
    a = manager.start(TwitchDownloadRequest(url=url))
    b = manager.start(TwitchDownloadRequest(url=url))
    assert a.id == b.id


def test_skip_existing_completes_without_download(manager):
    import reels.storage as storage_mod

    vods = storage_mod.temp_vods_dir()
    dest = vod_output_path("2222222222", vods)
    dest.write_bytes(b"\x00" * 5000)

    state = manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/2222222222"))
    assert state.status == "completed"
    assert state.path == str(dest.resolve())
    assert state.percent == 100.0


def test_parallel_queue_max_two_running(manager):
    gate = threading.Barrier(3)
    peak = {"n": 0}
    lock = threading.Lock()

    def counting_run(download_id: str, url: str) -> None:
        with lock:
            n = manager.running_count()
            peak["n"] = max(peak["n"], n)
        try:
            gate.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        state = manager._downloads[download_id]
        state.status = "completed"
        state.percent = 100.0

    with patch.object(TwitchDownloadManager, "_run", side_effect=counting_run):
        manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/1001"))
        manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/1002"))
        manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/1003"))
        time.sleep(0.25)

    assert peak["n"] <= 2


def test_cancel_queued_download(manager):
    hold = threading.Event()
    done = threading.Event()

    def hold_one(download_id: str, url: str) -> None:
        hold.wait(timeout=1)
        state = manager._downloads[download_id]
        state.status = "completed"
        done.set()

    with patch.object(TwitchDownloadManager, "_run", side_effect=hold_one):
        manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/3001"))
        manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/3002"))
        third = manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/3003"))
        time.sleep(0.05)

        cancelled = manager.cancel(third.id)
        assert cancelled.status == "cancelled"

        hold.set()
        done.wait(timeout=2)


def test_list_all_returns_downloads(manager):
    manager.start(TwitchDownloadRequest(url="https://www.twitch.tv/videos/4001"))
    items = manager.list_all()
    assert len(items) >= 1
    assert items[0].video_id == "4001"
