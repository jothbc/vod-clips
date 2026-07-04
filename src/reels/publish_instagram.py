"""Instagram Graph API Reels publishing."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

GRAPH = "https://graph.facebook.com/v21.0"


def _client_config(
    *,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> tuple[str, str, str]:
    app_id = client_id or os.environ.get("META_APP_ID", "")
    secret = client_secret or os.environ.get("META_APP_SECRET", "")
    redirect = redirect_uri or os.environ.get(
        "META_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v2/publish/oauth/callback/instagram",
    )
    if not app_id or not secret:
        raise ValueError(
            "Instagram OAuth not configured: add App ID and App Secret in the wallet card, "
            "or set META_APP_ID and META_APP_SECRET"
        )
    return app_id, secret, redirect


def build_auth_url(
    *,
    state: str,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> str:
    app_id, _secret, redirect_uri = _client_config(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
        "response_type": "code",
    }
    return f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"


def exchange_code(
    code: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    redirect_uri: str = "",
) -> dict[str, Any]:
    app_id, app_secret, redirect_uri = _client_config(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    with httpx.Client(timeout=60.0) as client:
        r = client.get(
            f"{GRAPH}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        r.raise_for_status()
        return r.json()


def publish_reel(
    access_token: str,
    ig_user_id: str,
    video_url: str,
    *,
    caption: str,
) -> str:
    """Two-step Reels publish using a public video URL."""
    if not ig_user_id:
        raise ValueError("Instagram ig_user_id is required in target config")
    with httpx.Client(timeout=120.0) as client:
        create = client.post(
            f"{GRAPH}/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
                "access_token": access_token,
            },
        )
        create.raise_for_status()
        container_id = create.json().get("id")
        if not container_id:
            raise RuntimeError("Instagram container creation failed")
        for _ in range(30):
            status = client.get(
                f"{GRAPH}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            status.raise_for_status()
            code = status.json().get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError("Instagram media processing failed")
            time.sleep(2)
        pub = client.post(
            f"{GRAPH}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        pub.raise_for_status()
        media_id = pub.json().get("id")
        if not media_id:
            raise RuntimeError("Instagram publish failed")
        return str(media_id)
