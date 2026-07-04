"""Publish wallet and deploy API routes."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from reels.jobs import get_job_manager
from reels.publish_deploy import create_deploy, deploy_to_dict, get_deploy, update_deploy
from reels.storage import temp_root
from reels.publish import load_publish
from reels.publish_instagram import build_auth_url as ig_auth_url
from reels.publish_instagram import exchange_code as ig_exchange_code
from reels.publish_tiktok import build_auth_url as tiktok_auth_url
from reels.publish_tiktok import exchange_code as tiktok_exchange_code
from reels.publish_wallet import (
    DEFAULT_OAUTH_REDIRECT,
    PublishPlatform,
    add_history,
    clear_credentials,
    create_target,
    delete_target,
    get_target,
    get_target_oauth_credentials,
    list_targets,
    load_credentials,
    save_credentials,
    update_target,
)
from reels.publish_youtube import (
    build_auth_url as yt_auth_url,
    exchange_code as yt_exchange_code,
    fetch_channel_label,
    refresh_access_token,
    set_thumbnail,
    test_upload_access,
    upload_video,
)

router = APIRouter(prefix="/api/v2/publish", tags=["publish-wallet"])

_oauth_states: dict[str, str] = {}


class CreateTargetBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    platform: PublishPlatform
    config: dict[str, Any] | None = None


class UpdateTargetBody(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class DeployBody(BaseModel):
    job_id: str | None = None
    session_id: str | None = None
    target_id: str
    item_index: int = 0
    overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_source(self) -> "DeployBody":
        if bool(self.job_id) == bool(self.session_id):
            raise ValueError("Provide exactly one of job_id or session_id")
        return self


def _oauth_kwargs(target) -> dict[str, str]:
    creds = get_target_oauth_credentials(target)
    return {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "redirect_uri": creds["redirect_uri"],
    }


def _auth_builder(platform: str, oauth: dict[str, str]):
    if platform == "youtube":
        return lambda state: yt_auth_url(state=state, **oauth)
    if platform == "tiktok":
        return lambda state: tiktok_auth_url(state=state, **oauth)
    if platform == "instagram":
        return lambda state: ig_auth_url(state=state, **oauth)
    raise ValueError(f"Unknown platform: {platform}")


def _exchange(platform: str, code: str, oauth: dict[str, str]) -> dict[str, Any]:
    if platform == "youtube":
        return yt_exchange_code(code, **oauth)
    if platform == "tiktok":
        return tiktok_exchange_code(code, **oauth)
    if platform == "instagram":
        return ig_exchange_code(code, **oauth)
    raise ValueError(f"Unknown platform: {platform}")


@router.get("/oauth/defaults")
def api_oauth_defaults() -> dict:
    return {"redirect_uris": DEFAULT_OAUTH_REDIRECT}


@router.get("/targets")
def api_list_targets() -> dict:
    return {"targets": [t.model_dump() for t in list_targets()]}


@router.post("/targets", status_code=201)
def api_create_target(body: CreateTargetBody) -> dict:
    target = create_target(label=body.label, platform=body.platform, config=body.config)
    return target.model_dump()


@router.patch("/targets/{target_id}")
def api_update_target(target_id: str, body: UpdateTargetBody) -> dict:
    try:
        target = update_target(
            target_id,
            label=body.label,
            enabled=body.enabled,
            config=body.config,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return target.model_dump()


@router.delete("/targets/{target_id}", status_code=204)
def api_delete_target(target_id: str) -> None:
    if not get_target(target_id):
        raise HTTPException(status_code=404, detail="Target not found")
    delete_target(target_id)


@router.post("/targets/{target_id}/disconnect")
def api_disconnect_target(target_id: str) -> dict:
    if not get_target(target_id):
        raise HTTPException(status_code=404, detail="Target not found")
    clear_credentials(target_id)
    target = get_target(target_id)
    assert target is not None
    return target.model_dump()


@router.post("/targets/{target_id}/test-upload")
def api_test_upload(target_id: str) -> dict:
    target = get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    if not target.connected:
        raise HTTPException(status_code=400, detail="Target is not connected")
    creds = load_credentials(target_id)
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=400, detail="Target is not connected")

    access = creds["access_token"]
    refresh = creds.get("refresh_token", "")
    oauth = _oauth_kwargs(target)

    if refresh and target.platform == "youtube":
        try:
            refreshed = refresh_access_token(
                refresh,
                client_id=oauth["client_id"],
                client_secret=oauth["client_secret"],
            )
            access = refreshed.get("access_token", access)
            save_credentials(
                target_id,
                access_token=access,
                refresh_token=refresh,
                account_label=creds.get("account_label", ""),
                account_id=creds.get("account_id", ""),
            )
        except Exception:
            pass

    if target.platform == "youtube":
        work_dir = temp_root() / "publish_tests" / target_id
        result = test_upload_access(access, work_dir)
        result["platform"] = "youtube"
        return result

    if target.platform == "tiktok":
        raise HTTPException(status_code=501, detail="Test upload not available for TikTok yet")

    if target.platform == "instagram":
        raise HTTPException(status_code=501, detail="Test upload not available for Instagram yet")

    raise HTTPException(status_code=400, detail="Unsupported platform")


@router.get("/targets/{target_id}/auth/start")
def api_auth_start(target_id: str) -> dict:
    target = get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    if target.platform not in ("youtube", "tiktok", "instagram"):
        raise HTTPException(status_code=400, detail="Unsupported platform")
    oauth = _oauth_kwargs(target)
    try:
        url = _auth_builder(target.platform, oauth)(state=target_id)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    _oauth_states[target_id] = target.platform
    return {"auth_url": url, "target_id": target_id}


@router.get("/oauth/callback/{platform}")
def api_oauth_callback(platform: Literal["youtube", "tiktok", "instagram"], code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    if error:
        return HTMLResponse(f"<html><body><p>OAuth error: {error}</p><script>window.close()</script></body></html>")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    target = get_target(state)
    if not target or target.platform != platform:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    oauth = _oauth_kwargs(target)
    try:
        token_data = _exchange(platform, code, oauth)
    except Exception as e:
        return HTMLResponse(
            f"<html><body><p>Falha ao conectar: {e}</p><script>window.close()</script></body></html>"
        )
    access = token_data.get("access_token", "")
    refresh = token_data.get("refresh_token", "")
    account_label = platform
    account_id = ""
    if platform == "youtube" and access:
        try:
            account_label, account_id = fetch_channel_label(access)
        except Exception:
            account_label = "YouTube"
    elif platform == "tiktok":
        account_label = "TikTok"
    elif platform == "instagram":
        account_label = "Instagram"
    save_credentials(
        state,
        access_token=access,
        refresh_token=refresh,
        scopes=json.dumps(token_data),
        account_label=account_label,
        account_id=account_id,
    )
    return HTMLResponse(
        "<html><body><p>Conta conectada. Pode fechar esta janela.</p>"
        "<script>window.opener && window.opener.postMessage('publish-oauth-done','*'); window.close();</script>"
        "</body></html>"
    )


def _resolve_publish_item(job_id: str, item_index: int):
    mgr = get_job_manager()
    state = mgr.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    manifest = Path(state.output_dir) / "publish" / "manifest.json"
    if not manifest.is_file():
        raise HTTPException(status_code=404, detail="Publish manifest not ready")
    doc = load_publish(manifest)
    if item_index < 0 or item_index >= len(doc.items):
        raise HTTPException(status_code=404, detail="Publish item not found")
    item = doc.items[item_index]
    video_path = Path(item.video_path)
    thumb_path = Path(item.thumbnail_path) if item.thumbnail_path else None
    video_id_param = ""
    ctx_path = Path(state.output_dir) / "v2_job_context.json"
    if ctx_path.is_file():
        try:
            ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
            video_id_param = str(ctx.get("source_video_id", ""))
        except json.JSONDecodeError:
            pass
    return state, doc, item, video_path, thumb_path, video_id_param


def _resolve_publish_session(session_id: str, item_index: int):
    from reels.publish_session import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    manifest = session.output_dir / "manifest.json"
    if not manifest.is_file():
        raise HTTPException(status_code=404, detail="Publish manifest not ready")
    doc = load_publish(manifest)
    if item_index < 0 or item_index >= len(doc.items):
        raise HTTPException(status_code=404, detail="Publish item not found")
    item = doc.items[item_index]
    video_path = Path(item.video_path)
    thumb_path = Path(item.thumbnail_path) if item.thumbnail_path else None
    return session, doc, item, video_path, thumb_path, session.video_id


def _execute_deploy(deploy_id: str, body: DeployBody) -> None:
    video_id_param = ""
    deploy_ref = body.session_id or body.job_id or ""
    try:
        target = get_target(body.target_id)
        if not target:
            raise RuntimeError("Target not found")

        if body.session_id:
            _session, doc, item, video_path, thumb_path, video_id_param = _resolve_publish_session(
                body.session_id, body.item_index
            )
            deploy_ref = body.session_id
        else:
            _state, doc, item, video_path, thumb_path, video_id_param = _resolve_publish_item(
                body.job_id or "", body.item_index
            )
            deploy_ref = body.job_id or ""

        overrides = body.overrides or {}
        title = str(overrides.get("title") or item.title)
        description = str(overrides.get("description") or item.description)
        tags = list(overrides.get("tags") or item.tags)

        creds = load_credentials(body.target_id)
        if not creds or not creds.get("access_token"):
            raise RuntimeError("Target is not connected")

        access = creds["access_token"]
        refresh = creds.get("refresh_token", "")
        oauth = _oauth_kwargs(target)

        update_deploy(deploy_id, phase="auth", percent=5, message="Autenticando…")

        if target.platform == "youtube":
            cfg = {**target.config, **overrides}
            if refresh:
                try:
                    refreshed = refresh_access_token(
                        refresh,
                        client_id=oauth["client_id"],
                        client_secret=oauth["client_secret"],
                    )
                    access = refreshed.get("access_token", access)
                    save_credentials(
                        body.target_id,
                        access_token=access,
                        refresh_token=refresh,
                        account_label=creds.get("account_label", ""),
                        account_id=creds.get("account_id", ""),
                    )
                except Exception:
                    pass

            youtube_format = str(overrides.get("youtube_format") or cfg.get("youtube_format") or "video")
            total_bytes = video_path.stat().st_size if video_path.is_file() else 0

            def on_upload_progress(ratio: float) -> None:
                pct = 10 + ratio * 75
                mb_done = int(ratio * total_bytes / (1024 * 1024)) if total_bytes else 0
                mb_total = int(total_bytes / (1024 * 1024)) if total_bytes else 0
                msg = f"Enviando vídeo… {mb_done}/{mb_total} MB" if mb_total else "Enviando vídeo…"
                update_deploy(deploy_id, phase="upload", percent=pct, message=msg)

            update_deploy(deploy_id, phase="upload", percent=10, message="Iniciando upload…")
            yt_id = upload_video(
                access,
                video_path,
                title=title,
                description=description,
                tags=tags,
                category_id=str(cfg.get("category_id", "20")),
                privacy=str(cfg.get("privacy", "unlisted")),
                made_for_kids=bool(cfg.get("made_for_kids", False)),
                language=str(cfg.get("default_language", "pt")),
                youtube_format=youtube_format,
                on_progress=on_upload_progress,
            )
            if thumb_path and thumb_path.is_file():
                update_deploy(deploy_id, phase="thumbnail", percent=90, message="Enviando capa…")
                try:
                    set_thumbnail(access, yt_id, thumb_path)
                except Exception:
                    pass
            watch_url = f"https://www.youtube.com/watch?v={yt_id}"
            add_history(
                target_id=body.target_id,
                video_id=video_id_param,
                job_id=deploy_ref,
                status="published",
                platform_post_id=yt_id,
            )
            update_deploy(
                deploy_id,
                status="completed",
                phase="done",
                percent=100,
                message="Publicado com sucesso",
                result={"platform_post_id": yt_id, "watch_url": watch_url},
            )
            return

        if target.platform == "tiktok":
            from reels.publish_tiktok import publish_video as tiktok_publish

            update_deploy(deploy_id, phase="upload", percent=20, message="Enviando para TikTok…")
            cfg = {**target.config, **overrides}
            caption = title if doc.platform == "short_form" else f"{title}\n\n{description}"[:150]
            pub_id = tiktok_publish(
                access,
                str(video_path),
                title=caption,
                privacy_level=str(cfg.get("privacy_level", "PUBLIC_TO_EVERYONE")),
                disable_comment=bool(cfg.get("disable_comment", False)),
                disable_duet=bool(cfg.get("disable_duet", False)),
            )
            add_history(
                target_id=body.target_id,
                video_id=video_id_param,
                job_id=deploy_ref,
                status="published",
                platform_post_id=pub_id,
            )
            update_deploy(
                deploy_id,
                status="completed",
                phase="done",
                percent=100,
                message="Publicado com sucesso",
                result={"platform_post_id": pub_id, "watch_url": ""},
            )
            return

        if target.platform == "instagram":
            raise RuntimeError("Instagram deploy requires a public video URL; use export package for now")

        raise RuntimeError("Unsupported platform")
    except Exception as e:
        add_history(
            target_id=body.target_id,
            video_id=video_id_param,
            job_id=deploy_ref,
            status="failed",
            error=str(e),
        )
        update_deploy(deploy_id, status="failed", phase="failed", message="Falha ao publicar", error=str(e))


@router.post("/deploy")
def api_deploy(body: DeployBody) -> dict:
    target = get_target(body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    if not target.enabled:
        raise HTTPException(status_code=400, detail="Target is disabled")
    creds = load_credentials(body.target_id)
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=400, detail="Target is not connected")

    if body.session_id:
        _resolve_publish_session(body.session_id, body.item_index)
    else:
        _resolve_publish_item(body.job_id or "", body.item_index)

    rec = create_deploy()
    thread = threading.Thread(target=_execute_deploy, args=(rec.id, body), daemon=True)
    thread.start()
    return deploy_to_dict(rec)


@router.get("/deploy/{deploy_id}")
def api_deploy_status(deploy_id: str) -> dict:
    rec = get_deploy(deploy_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Deploy not found")
    return deploy_to_dict(rec)
