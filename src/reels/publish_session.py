"""Ephemeral publish compose sessions (manual fields + per-field AI)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reels.models import PublishDocument, PublishItem
from reels.publish import write_publish
from reels.storage import temp_root


@dataclass
class PublishSession:
    id: str
    video_id: str
    video_path: str
    output_dir: Path


def _sessions_root() -> Path:
    d = temp_root() / "publish_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_meta_path(session_id: str) -> Path:
    return _sessions_root() / session_id / "session.json"


def create_session(*, video_id: str, video_path: Path) -> PublishSession:
    sid = uuid.uuid4().hex[:12]
    out = _sessions_root() / sid
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": sid,
        "video_id": video_id,
        "video_path": str(video_path),
    }
    _session_meta_path(sid).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    draft = PublishDocument(
        platform="youtube",
        items=[
            PublishItem(
                video_path=str(video_path),
                source_label=video_path.name,
                platform="youtube",
            )
        ],
    )
    write_publish(out / "manifest.json", draft)
    return PublishSession(id=sid, video_id=video_id, video_path=str(video_path), output_dir=out)


def get_session(session_id: str) -> PublishSession | None:
    path = _session_meta_path(session_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    out = _sessions_root() / session_id
    if not out.is_dir():
        return None
    return PublishSession(
        id=session_id,
        video_id=str(data["video_id"]),
        video_path=str(data["video_path"]),
        output_dir=out,
    )


def update_draft(
    session_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    platform: str | None = None,
    thumbnail_path: str | None = None,
    thumbnail_timestamp: float | None = None,
) -> None:
    from reels.publish import load_publish

    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")
    manifest = session.output_dir / "manifest.json"
    doc = load_publish(manifest)
    if platform:
        doc.platform = platform
    if doc.items:
        item = doc.items[0]
        if title is not None:
            item.title = title
        if description is not None:
            item.description = description
        if tags is not None:
            item.tags = tags
        if platform:
            item.platform = platform
        if thumbnail_path is not None:
            item.thumbnail_path = thumbnail_path
        if thumbnail_timestamp is not None:
            item.thumbnail_timestamp = thumbnail_timestamp
    write_publish(manifest, doc)

