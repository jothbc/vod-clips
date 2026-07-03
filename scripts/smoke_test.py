#!/usr/bin/env python3
"""End-to-end smoke test against a running reels API."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Force line-buffered stdout when piped (PowerShell Tee-Object).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

API = "http://127.0.0.1:8000"
VIDEO = Path(__file__).resolve().parents[1] / "temp" / "vods" / "smoke_5min.mp4"
POLL_INTERVAL = 3.0
JOB_TIMEOUT = 2400  # 40 min per job (CPU Whisper on 5 min VOD)


class SmokeError(Exception):
    pass


def api(method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        try:
            parsed = json.loads(detail)
            detail = parsed.get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise SmokeError(f"{method} {path} -> {e.code}: {detail}") from e


def wait_api(max_wait: float = 30) -> None:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = api("GET", "/api/ready")
            if r.get("ok"):
                return
        except Exception:
            pass
        time.sleep(1)
    raise SmokeError("API not ready")


def wait_job(job_id: str, label: str) -> dict:
    deadline = time.time() + JOB_TIMEOUT
    last_phase = ""
    while time.time() < deadline:
        state = api("GET", f"/api/jobs/{job_id}")
        phase = state.get("phase", "")
        pct = state.get("percent", 0)
        if phase != last_phase:
            print(f"  [{label}] {state.get('status')} | {phase} | {pct}% | {state.get('message', '')}")
            last_phase = phase
        if state.get("status") == "completed":
            return state
        if state.get("status") in ("failed", "cancelled"):
            raise SmokeError(f"{label} failed: {state.get('error') or state.get('message')}")
        time.sleep(POLL_INTERVAL)
    try:
        api("POST", "/api/session/reset", {"cleanup_previous": False})
    except Exception:
        pass
    raise SmokeError(f"{label} timed out after {JOB_TIMEOUT}s")


def check(name: str, fn) -> bool:
    print(f"\n== {name} ==")
    try:
        fn()
        print(f"OK: {name}")
        return True
    except Exception as e:
        print(f"FAIL: {name} -> {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Reels E2E smoke test")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[
            "health",
            "features",
            "vods",
            "fonts",
            "reels",
            "library",
            "cleanup",
            "captions",
            "publish",
            "reset",
        ],
        help="Run only selected steps (default: all)",
    )
    args = parser.parse_args()
    only = set(args.only) if args.only else None

    def want(step: str) -> bool:
        return only is None or step in only

    if not VIDEO.is_file():
        print(f"Missing smoke video: {VIDEO}", file=sys.stderr)
        return 1

    print(f"Smoke video: {VIDEO} ({VIDEO.stat().st_size / 1024**2:.1f} MB)")
    wait_api()
    results: list[bool] = []

    def test_health():
        h = api("GET", "/api/health")
        assert h.get("ffmpeg") is True, "ffmpeg missing"
        print(f"  ffmpeg={h['ffmpeg']} ollama={h.get('ollama')} yt_dlp={h.get('yt_dlp')}")

    def test_features():
        feats = api("GET", "/api/features")["features"]
        ids = {f["id"] for f in feats}
        for fid in ("gallery", "reels", "cleanup", "captions", "publish"):
            assert fid in ids, f"missing feature {fid}"
        print(f"  features: {sorted(ids)}")

    def test_vods():
        listed = api("GET", "/api/vods")
        paths = [v["path"] for v in listed["vods"]]
        assert str(VIDEO.resolve()) in paths or any("smoke_5min" in p for p in paths)
        print(f"  {len(listed['vods'])} VOD(s) in {listed['dir']}")

    def test_caption_fonts():
        fonts = api("GET", "/api/captions/fonts")["fonts"]
        assert len(fonts) >= 1
        print(f"  {len(fonts)} font(s)")

    reels_job_id: str | None = None

    def test_reels():
        nonlocal reels_job_id
        r = api(
            "POST",
            "/api/jobs",
            {
                "video_path": str(VIDEO.resolve()),
                "feature": "reels",
                "preset": "smoke",
                "mode": "gaming",
                "max_clips": 2,
            },
        )
        reels_job_id = r["job_id"]
        print(f"  job_id={reels_job_id}")
        wait_job(reels_job_id, "reels")
        hl = api("GET", f"/api/jobs/{reels_job_id}/highlights")
        assert hl["highlights"], "no highlights"
        print(f"  {len(hl['highlights'])} highlight(s)")
        api(
            "POST",
            f"/api/jobs/{reels_job_id}/export",
            {"highlight_indices": [0], "use_nvenc": False},
        )
        wait_job(reels_job_id, "reels-export")
        clips = api("GET", f"/api/jobs/{reels_job_id}/clips")
        assert clips["clips"], "no exported clips"
        url = clips["clips"][0].get("youtube_url") or clips["clips"][0].get("reels_url")
        assert url, "clip has no media url"
        media = api("GET", url.replace(API, ""), timeout=30) if url.startswith("http") else None
        # HEAD-like check via GET /media
        req = urllib.request.Request(f"{API}{url}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 200
            assert resp.headers.get("content-type", "").startswith("video/")
        print(f"  exported clip served at {url}")

    def test_library():
        lib = api("GET", "/api/reels/library")
        assert lib["jobs"], "library empty after reels export"
        pick = api("GET", "/api/reels/pickable-clips")
        assert pick["clips"], "no pickable clips"
        print(f"  library jobs={len(lib['jobs'])} pickable={len(pick['clips'])}")

    cleanup_job_id: str | None = None

    def test_cleanup():
        nonlocal cleanup_job_id
        r = api(
            "POST",
            "/api/jobs",
            {
                "video_path": str(VIDEO.resolve()),
                "feature": "cleanup",
                "preset": "smoke",
                "use_nvenc": False,
            },
        )
        cleanup_job_id = r["job_id"]
        wait_job(cleanup_job_id, "cleanup")
        edl = api("GET", f"/api/jobs/{cleanup_job_id}/edl")
        assert edl["spans"], "empty EDL"
        cuts = [s["index"] for s in edl["spans"] if s["kind"] == "cut"]
        print(f"  EDL spans={len(edl['spans'])} proposed cuts={len(cuts)}")
        api(
            "POST",
            f"/api/jobs/{cleanup_job_id}/render",
            {"cut_indices": cuts[: min(3, len(cuts))], "use_nvenc": False},
        )
        wait_job(cleanup_job_id, "cleanup-render")
        final = api("GET", f"/api/jobs/{cleanup_job_id}/final")
        assert final["videos"], "no final videos"
        print(f"  final formats: {[v['format'] for v in final['videos']]}")

    captions_job_id: str | None = None

    def test_captions():
        nonlocal captions_job_id
        r = api(
            "POST",
            "/api/jobs",
            {
                "video_path": str(VIDEO.resolve()),
                "feature": "captions",
                "preset": "smoke",
                "use_nvenc": False,
            },
        )
        captions_job_id = r["job_id"]
        wait_job(captions_job_id, "captions")
        caps = api("GET", f"/api/jobs/{captions_job_id}/captions")
        assert caps["segments"], "no caption segments"
        print(f"  {len(caps['segments'])} segment(s)")
        api(
            "PUT",
            f"/api/jobs/{captions_job_id}/captions",
            {"segments": caps["segments"], "font_id": "montserrat-bold"},
        )
        api(
            "POST",
            f"/api/jobs/{captions_job_id}/render-captions",
            {"font_id": "montserrat-bold", "use_nvenc": False},
        )
        wait_job(captions_job_id, "captions-render")
        cap = api("GET", f"/api/jobs/{captions_job_id}/captioned")
        assert cap.get("url")
        print(f"  captioned video: {cap['url']}")

    def test_publish():
        clips = api("GET", "/api/reels/pickable-clips")["clips"]
        clip_path = clips[0]["path"] if clips else str(VIDEO.resolve())
        r = api(
            "POST",
            "/api/jobs",
            {
                "video_path": clip_path,
                "feature": "publish",
                "preset": "smoke",
                "params": {
                    "video_paths": [clip_path],
                    "platform": "youtube",
                    "content_type": "game",
                    "game_name": "Smoke Test Game",
                },
            },
        )
        pub_id = r["job_id"]
        wait_job(pub_id, "publish")
        pub = api("GET", f"/api/jobs/{pub_id}/publish")
        assert pub["items"], "no publish items"
        item = pub["items"][0]
        assert item.get("title")
        thumb_url = item.get("thumbnail_url")
        if thumb_url:
            req = urllib.request.Request(f"{API}{thumb_url}")
            with urllib.request.urlopen(req, timeout=30) as resp:
                assert resp.status == 200
        print(f"  title={item['title'][:60]!r} tags={item.get('tags', [])}")

    def test_session_reset():
        r = api("POST", "/api/session/reset", {"cleanup_previous": False})
        assert r.get("cancelled") is True

    if want("health"):
        results.append(check("health", test_health))
    if want("features"):
        results.append(check("features", test_features))
    if want("vods"):
        results.append(check("vods / gallery ingest", test_vods))
    if want("fonts"):
        results.append(check("caption fonts", test_caption_fonts))
    if want("reels"):
        results.append(check("reels (analyze + export + media)", test_reels))
    if want("library"):
        results.append(check("reels library + pickable clips", test_library))
    if want("cleanup"):
        results.append(check("cleanup (EDL + render)", test_cleanup))
    if want("captions"):
        results.append(check("captions (edit + burn-in)", test_captions))
    if want("publish"):
        results.append(check("publish (metadata + thumbnail)", test_publish))
    if want("reset"):
        results.append(check("session reset", test_session_reset))

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 40}")
    print(f"Smoke test: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
