"""TikTok Content Posting API integration."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import httpx

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_UPLOAD_INIT = "https://open.tiktokapis.com/v2/post/publish/video/init/"


def _client_config(
    *,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> tuple[str, str, str]:
    client_key = client_id or os.environ.get("TIKTOK_CLIENT_KEY", "")
    secret = client_secret or os.environ.get("TIKTOK_CLIENT_SECRET", "")
    redirect = redirect_uri or os.environ.get(
        "TIKTOK_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v2/publish/oauth/callback/tiktok",
    )
    if not client_key or not secret:
        raise ValueError(
            "TikTok OAuth not configured: add Client Key and Client Secret in the wallet card, "
            "or set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET"
        )
    return client_key, secret, redirect


def build_auth_url(
    *,
    state: str,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> str:
    client_key, _secret, redirect_uri = _client_config(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": "video.publish,video.upload",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{TIKTOK_AUTH_URL}?{urlencode(params)}"


def exchange_code(
    code: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> dict[str, Any]:
    client_key, client_secret, redirect_uri = _client_config(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            TIKTOK_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        r.raise_for_status()
        return r.json()


def publish_video(
    access_token: str,
    video_path: str,
    *,
    title: str,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    disable_comment: bool = False,
    disable_duet: bool = False,
) -> str:
    """Init direct post flow; returns publish_id when available."""
    from pathlib import Path

    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(video_path)
    size = path.stat().st_size
    with httpx.Client(timeout=600.0) as client:
        init = client.post(
            TIKTOK_UPLOAD_INIT,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "post_info": {
                    "title": title[:150],
                    "privacy_level": privacy_level,
                    "disable_comment": disable_comment,
                    "disable_duet": disable_duet,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": min(size, 10 * 1024 * 1024),
                    "total_chunk_count": 1,
                },
            },
        )
        init.raise_for_status()
        data = init.json()
        publish_id = (data.get("data") or {}).get("publish_id") or data.get("publish_id")
        upload_url = (data.get("data") or {}).get("upload_url")
        if not upload_url:
            raise RuntimeError(f"TikTok init missing upload_url: {data}")
        with path.open("rb") as f:
            up = client.put(upload_url, content=f.read())
        up.raise_for_status()
        return str(publish_id or "tiktok_pending")
