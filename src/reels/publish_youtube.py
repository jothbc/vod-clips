"""YouTube OAuth and resumable upload via HTTP APIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlencode

import httpx

YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/youtube.force-ssl"
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
UPLOAD_INIT = "https://www.googleapis.com/upload/youtube/v3/videos"
API_BASE = "https://www.googleapis.com/youtube/v3"


def format_youtube_error(response: httpx.Response) -> str:
    """Turn a YouTube API error response into a user-facing message."""
    try:
        data = response.json()
        err = data.get("error") or {}
        message = str(err.get("message") or response.text or response.reason_phrase)
        reasons = [
            str(e.get("reason", ""))
            for e in (err.get("errors") or [])
            if e.get("reason")
        ]
        hint = ""
        joined = " ".join(reasons).lower()
        if response.status_code == 403:
            if "youtube" in joined or "upload" in message.lower():
                hint = (
                    " Verifique se a YouTube Data API v3 está ativada no Google Cloud, "
                    "se o app OAuth não está em modo de teste sem seu e-mail como testador, "
                    "e se a conta conectada tem permissão de upload."
                )
            elif "quota" in joined or "quota" in message.lower():
                hint = " Cota diária da API pode estar esgotada."
        if reasons:
            return f"YouTube API ({response.status_code}): {message} [{', '.join(reasons)}]{hint}"
        return f"YouTube API ({response.status_code}): {message}{hint}"
    except Exception:
        return f"YouTube API ({response.status_code}): {response.text[:300] or response.reason_phrase}"


def _raise_for_youtube(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise RuntimeError(format_youtube_error(response))


def _client_config(
    *,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> tuple[str, str, str]:
    cid = client_id or os.environ.get("GOOGLE_CLIENT_ID", "")
    secret = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect = redirect_uri or os.environ.get(
        "OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v2/publish/oauth/callback/youtube",
    )
    if not cid or not secret:
        raise ValueError(
            "YouTube OAuth not configured: add Client ID and Client Secret in the wallet card, "
            "or set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"
        )
    return cid, secret, redirect


def build_auth_url(
    *,
    state: str,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> str:
    cid, _secret, redirect = _client_config(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": YOUTUBE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(
    code: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> dict[str, Any]:
    cid, secret, redirect = _client_config(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": cid,
                "client_secret": secret,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
        )
        r.raise_for_status()
        return r.json()


def refresh_access_token(
    refresh_token: str,
    *,
    client_id: str = "",
    client_secret: str = "",
) -> dict[str, Any]:
    cid, secret, _redirect = _client_config(client_id=client_id, client_secret=client_secret)
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        r.raise_for_status()
        return r.json()


def fetch_channel_label(access_token: str) -> tuple[str, str]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{API_BASE}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        _raise_for_youtube(r)
        data = r.json()
        items = data.get("items") or []
        if not items:
            return "YouTube", ""
        ch = items[0]
        title = ch.get("snippet", {}).get("title") or "YouTube"
        return title, ch.get("id", "")


def _ensure_minimal_test_mp4(path: Path) -> None:
    import subprocess

    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            "1",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not path.is_file():
        raise RuntimeError("ffmpeg is required for upload test")


def init_resumable_upload(
    access_token: str,
    video_path: Path,
    *,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
    privacy: str = "private",
    made_for_kids: bool = False,
    language: str = "pt",
) -> str:
    """Start a resumable upload session; returns the upload URL (does not transfer bytes)."""
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": category_id,
            "defaultLanguage": language,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
    }
    with httpx.Client(timeout=120.0) as client:
        init = client.post(
            UPLOAD_INIT,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            content=json.dumps(metadata),
        )
        _raise_for_youtube(init)
        upload_url = init.headers.get("Location")
        if not upload_url:
            raise RuntimeError("YouTube upload session missing Location header")
        return upload_url


def apply_youtube_format(
    title: str,
    description: str,
    tags: list[str],
    youtube_format: str,
) -> tuple[str, str, list[str]]:
    """Adjust metadata so vertical Shorts are classified correctly on YouTube."""
    if youtube_format != "shorts":
        return title, description, tags
    out_title = title
    out_desc = description
    out_tags = list(tags)
    if "#shorts" not in out_desc.lower() and "#shorts" not in out_title.lower():
        out_desc = f"{out_desc.rstrip()}\n\n#Shorts".strip() if out_desc.strip() else "#Shorts"
    if not any(t.lower() == "shorts" for t in out_tags):
        out_tags = ["Shorts", *out_tags][:30]
    return out_title, out_desc, out_tags


def _upload_resumable(
    access_token: str,
    upload_url: str,
    video_path: Path,
    *,
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    total = video_path.stat().st_size
    if total <= 0:
        raise RuntimeError("Video file is empty")
    chunk_size = 256 * 1024
    uploaded = 0
    with httpx.Client(timeout=600.0) as client:
        with video_path.open("rb") as f:
            while uploaded < total:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                start = uploaded
                end = uploaded + len(chunk) - 1
                headers: dict[str, str] = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                }
                if total > len(chunk) or end < total - 1:
                    headers["Content-Range"] = f"bytes {start}-{end}/{total}"
                r = client.put(upload_url, headers=headers, content=chunk)
                if r.status_code == 308:
                    uploaded = end + 1
                elif r.status_code in (200, 201):
                    uploaded = total
                    _raise_for_youtube(r)
                    return r.json() if r.content else {}
                else:
                    _raise_for_youtube(r)
                    return r.json() if r.content else {}
                if on_progress:
                    on_progress(min(1.0, uploaded / total))
    raise RuntimeError("YouTube upload incomplete")


def test_upload_access(access_token: str, work_dir: Path) -> dict[str, Any]:
    """Validate channel access and resumable upload permission without publishing a video."""
    checks: list[dict[str, Any]] = []
    channel_title = ""
    channel_id = ""
    try:
        channel_title, channel_id = fetch_channel_label(access_token)
        checks.append(
            {
                "name": "channel",
                "ok": True,
                "detail": channel_title or "Canal encontrado",
            }
        )
    except Exception as e:
        checks.append({"name": "channel", "ok": False, "detail": str(e)})
        return {"ok": False, "checks": checks, "channel_title": "", "channel_id": ""}

    test_mp4 = work_dir / "_upload_test.mp4"
    try:
        _ensure_minimal_test_mp4(test_mp4)
        init_resumable_upload(
            access_token,
            test_mp4,
            title="Reels upload test (discard)",
            description="Connectivity test — do not publish",
            privacy="private",
        )
        checks.append(
            {
                "name": "upload_init",
                "ok": True,
                "detail": "Permissão de upload confirmada",
            }
        )
    except Exception as e:
        checks.append({"name": "upload_init", "ok": False, "detail": str(e)})

    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "checks": checks,
        "channel_title": channel_title,
        "channel_id": channel_id,
    }


def upload_video(
    access_token: str,
    video_path: Path,
    *,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "20",
    privacy: str = "unlisted",
    made_for_kids: bool = False,
    language: str = "pt",
    youtube_format: str = "video",
    on_progress: Callable[[float], None] | None = None,
) -> str:
    """Resumable upload; returns YouTube video id."""
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))
    title, description, tags = apply_youtube_format(title, description, tags, youtube_format)
    upload_url = init_resumable_upload(
        access_token,
        video_path,
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy=privacy,
        made_for_kids=made_for_kids,
        language=language,
    )
    body = _upload_resumable(access_token, upload_url, video_path, on_progress=on_progress)
    vid = body.get("id")
    if not vid:
        raise RuntimeError("YouTube upload response missing video id")
    return str(vid)


def set_thumbnail(access_token: str, video_id: str, thumbnail_path: Path) -> None:
    if not thumbnail_path.is_file():
        return
    url = f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
    with httpx.Client(timeout=120.0) as client:
        with thumbnail_path.open("rb") as f:
            r = client.post(
                url,
                params={"videoId": video_id},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "image/jpeg",
                },
                content=f.read(),
            )
        if r.status_code >= 400:
            raise RuntimeError(f"YouTube thumbnail upload failed: {r.text[:200]}")
