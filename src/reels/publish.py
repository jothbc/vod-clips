"""Publishing metadata generation and manifest I/O."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
