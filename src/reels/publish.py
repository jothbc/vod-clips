"""Publishing metadata generation and manifest I/O."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from reels.config import AppConfig, prompts_path
from reels.models import PublishDocument, PublishItem, VideoInfo
from reels.vlm.ollama import _fill_prompt


@dataclass
class PublishContext:
    content_type: str = "game"
    game_name: str = ""
    video_context: str = ""
    channel_info: str = ""


def parse_publish_context(data: dict[str, Any]) -> PublishContext:
    return PublishContext(
        content_type=str(data.get("content_type", "game")),
        game_name=str(data.get("game_name", "")),
        video_context=str(data.get("video_context", "")),
        channel_info=str(data.get("channel_info", "")),
    )


def format_subject_context_block(ctx: PublishContext) -> str:
    if ctx.content_type == "other":
        return ctx.video_context
    if ctx.game_name:
        return ctx.game_name
    return ctx.video_context


def build_transcript_summary(segments: list[dict[str, Any]], max_chars: int = 4000) -> str:
    text = " ".join(str(seg.get("text", "")) for seg in segments).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _extract_metadata_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _fallback_metadata(
    segments: list[dict[str, Any]],
    info: VideoInfo,
    platform: str,
    config: AppConfig,
) -> dict[str, Any]:
    summary = build_transcript_summary(segments, max_chars=200)
    words = summary.split()
    title_max = (
        config.publish.youtube_title_max
        if platform == "youtube"
        else config.publish.short_title_max
    )
    title = " ".join(words[:12]) or Path(info.path).stem
    if len(title) > title_max:
        title = title[: title_max - 3] + "..."
    return {
        "title": title,
        "description": summary,
        "tags": [],
        "thumbnail_second": round(info.duration * 0.3, 1),
    }


def generate_metadata(
    client: Any,
    config: AppConfig,
    segments: list[dict[str, Any]],
    platform: str,
    info: VideoInfo,
    context: PublishContext | None = None,
) -> tuple[dict[str, Any], bool]:
    """Generate title/description/tags; returns (metadata, llm_used)."""
    ctx = context or PublishContext()
    if not client.is_available():
        return _fallback_metadata(segments, info, platform, config), False

    prompt_name = (
        "publish_youtube.txt" if platform == "youtube" else "publish_short_form.txt"
    )
    template = prompts_path(config, prompt_name).read_text(encoding="utf-8")
    title_max = (
        config.publish.youtube_title_max
        if platform == "youtube"
        else config.publish.short_title_max
    )
    prompt = _fill_prompt(
        template,
        title_max=title_max,
        channel_info=ctx.channel_info or "(not provided)",
        subject_context=format_subject_context_block(ctx) or "(not provided)",
        duration=round(info.duration, 1),
        width=info.width,
        height=info.height,
        transcript=build_transcript_summary(segments),
    )
    try:
        reply = client.chat_text(prompt, model=config.publish.llm_model)
    except Exception:
        return _fallback_metadata(segments, info, platform, config), False

    data = _extract_metadata_json(reply)
    if not data.get("title"):
        return _fallback_metadata(segments, info, platform, config), False

    return {
        "title": str(data.get("title", "")),
        "description": str(data.get("description", "")),
        "tags": list(data.get("tags") or []),
        "thumbnail_second": float(data.get("thumbnail_second", info.duration * 0.3)),
    }, True


def slug_from_path(path: str | Path, index: int) -> str:
    stem = Path(path).stem
    safe = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_")
    safe = re.sub(r"_+", "_", safe) or "clip"
    return f"{index:02d}_{safe}"


def load_publish(path: Path | str) -> PublishDocument:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PublishDocument.model_validate(data)


def write_publish(path: Path | str, doc: PublishDocument) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc.model_dump_json(indent=2), encoding="utf-8")


PublishField = Literal["title", "description", "tags", "thumbnail"]


def _field_prompt(
    field: PublishField,
    *,
    platform: str,
    config: AppConfig,
    ctx: PublishContext,
    segments: list[dict[str, Any]],
    info: VideoInfo,
    title_hint: str = "",
) -> str:
    transcript = build_transcript_summary(segments)
    subject = format_subject_context_block(ctx) or "(not provided)"
    channel = ctx.channel_info or "(not provided)"
    title_max = (
        config.publish.youtube_title_max
        if platform == "youtube"
        else config.publish.short_title_max
    )
    if field == "title":
        return (
            f"You are a YouTube strategist. Write ONE catchy title in Brazilian Portuguese (PT-BR), "
            f"max {title_max} chars, for platform={platform}.\n"
            f"Subject: {subject}\nChannel: {channel}\nDuration: {info.duration}s\n"
            f"Transcript excerpt:\n{transcript}\n\n"
            'Return ONLY JSON: {"title": "..."}'
        )
    if field == "description":
        return (
            "Write a YouTube video description in Brazilian Portuguese (PT-BR): 2-4 short paragraphs, "
            "hook first line, hashtags at end.\n"
            f"Subject: {subject}\nChannel: {channel}\nTitle hint: {title_hint or '(none)'}\n"
            f"Transcript excerpt:\n{transcript}\n\n"
            'Return ONLY JSON: {"description": "..."}'
        )
    if field == "tags":
        return (
            "Suggest 5-12 YouTube tags in Brazilian Portuguese (no # prefix).\n"
            f"Subject: {subject}\nChannel: {channel}\nTitle: {title_hint or '(none)'}\n"
            f"Transcript excerpt:\n{transcript[:2000]}\n\n"
            'Return ONLY JSON: {"tags": ["tag1", "tag2"]}'
        )
    return (
        "Pick the best thumbnail timestamp (seconds) for this video — visually engaging hook moment.\n"
        f"Duration: {info.duration}s\nSubject: {subject}\n"
        f"Transcript excerpt:\n{transcript[:2000]}\n\n"
        'Return ONLY JSON: {"thumbnail_second": 42.5}'
    )


def suggest_publish_field(
    field: PublishField,
    *,
    client: Any,
    config: AppConfig,
    segments: list[dict[str, Any]],
    platform: str,
    info: VideoInfo,
    context: PublishContext | None = None,
    title_hint: str = "",
) -> dict[str, Any]:
    """Generate a single field suggestion. Returns partial metadata dict."""
    ctx = context or PublishContext()
    if field in ("title", "description", "tags", "thumbnail") and not client.is_available():
        fb = _fallback_metadata(segments, info, platform, config)
        if field == "title":
            return {"title": fb["title"]}
        if field == "description":
            return {"description": fb["description"]}
        if field == "tags":
            return {"tags": fb["tags"]}
        return {"thumbnail_second": fb["thumbnail_second"]}

    prompt = _field_prompt(
        field,
        platform=platform,
        config=config,
        ctx=ctx,
        segments=segments,
        info=info,
        title_hint=title_hint,
    )
    try:
        reply = client.chat_text(prompt, model=config.publish.llm_model)
    except Exception:
        fb = _fallback_metadata(segments, info, platform, config)
        key = field if field != "thumbnail" else "thumbnail_second"
        if field == "tags":
            return {"tags": fb["tags"]}
        if field == "thumbnail":
            return {"thumbnail_second": fb["thumbnail_second"]}
        return {field: fb[field]}

    data = _extract_metadata_json(reply)
    if field == "title" and data.get("title"):
        return {"title": str(data["title"])}
    if field == "description" and data.get("description"):
        return {"description": str(data["description"])}
    if field == "tags" and data.get("tags") is not None:
        return {"tags": [str(t) for t in data.get("tags") or []]}
    if field == "thumbnail" and data.get("thumbnail_second") is not None:
        return {"thumbnail_second": float(data["thumbnail_second"])}
    fb = _fallback_metadata(segments, info, platform, config)
    if field == "thumbnail":
        return {"thumbnail_second": fb["thumbnail_second"]}
    if field == "tags":
        return {"tags": fb["tags"]}
    return {field: fb[field]}


def render_publish_thumbnail(
    video_path: Path,
    output_dir: Path,
    *,
    title: str,
    platform: str,
    config: AppConfig,
    timestamp: float | None = None,
) -> tuple[Path, float]:
    """Extract frame and overlay title; returns (thumbnail path, timestamp used)."""
    import subprocess

    from reels.probe import probe_video
    from reels.thumbnail import overlay_title_on_image

    info = probe_video(video_path)
    ts = timestamp if timestamp is not None else info.duration * 0.3
    ts = max(0.0, min(ts, max(0.01, info.duration - 0.1)))
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_path = output_dir / "frame.jpg"
    thumb_path = output_dir / "thumbnail.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(ts),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ],
        capture_output=True,
        check=False,
    )
    if frame_path.is_file():
        overlay_title_on_image(
            frame_path,
            title or video_path.stem,
            thumb_path,
            config=config,
            platform=platform,
            work_dir=output_dir,
            frame_height=info.height,
        )
    elif not thumb_path.is_file():
        raise RuntimeError("Could not extract thumbnail frame")
    return thumb_path, ts
