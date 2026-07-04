"""Publish metadata feature tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.config import load_config
from reels.jobs import JobManager, JobState, JobStatus
from reels.models import PublishDocument, PublishItem, VideoInfo
from reels.publish import (
    PublishContext,
    build_transcript_summary,
    format_subject_context_block,
    generate_metadata,
    load_publish,
    parse_publish_context,
    slug_from_path,
    suggest_publish_field,
    write_publish,
)
from reels.thumbnail import target_dimensions, wrap_title_lines


@pytest.fixture
def client(monkeypatch):
    import reels.jobs as jobs_mod
    import reels.twitch.manager as twitch_mod

    jobs_mod._manager = JobManager()
    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)
    c = TestClient(create_app())
    yield c
    jobs_mod.get_job_manager()._running = False


def test_build_transcript_summary_caps_length():
    segments = [{"text": "word " * 500}]
    summary = build_transcript_summary(segments, max_chars=100)
    assert len(summary) <= 100
    assert summary.endswith("...")


def test_generate_metadata_parses_llm_json():
    config = load_config()
    info = VideoInfo(path="/tmp/v.mp4", duration=120.0, width=1920, height=1080, fps=30.0)
    segments = [{"text": "This is an amazing gaming moment"}]
    client = MagicMock()
    client.is_available.return_value = True
    client.chat_text.return_value = json.dumps(
        {
            "title": "Epic Gaming Moment",
            "description": "Watch this clip\n\n#gaming",
            "tags": ["gaming", "highlights"],
            "thumbnail_second": 15.5,
        }
    )
    meta, ok = generate_metadata(client, config, segments, "youtube", info)
    assert ok is True
    assert meta["title"] == "Epic Gaming Moment"
    assert meta["tags"] == ["gaming", "highlights"]
    assert meta["thumbnail_second"] == 15.5


def test_generate_metadata_fallback_when_llm_offline():
    config = load_config()
    info = VideoInfo(path="/tmp/v.mp4", duration=100.0, width=1080, height=1920, fps=30.0)
    segments = [{"text": "Hello world from the stream"}]
    client = MagicMock()
    client.is_available.return_value = False
    meta, ok = generate_metadata(client, config, segments, "short_form", info)
    assert ok is False
    assert "Hello world" in meta["title"]
    assert meta["thumbnail_second"] == pytest.approx(30.0)


def test_generate_metadata_uses_short_form_prompt():
    config = load_config()
    info = VideoInfo(path="/tmp/clip.mp4", duration=30.0, width=1080, height=1920, fps=30.0)
    segments = [{"text": "Quick viral hook"}]
    client = MagicMock()
    client.is_available.return_value = True
    client.chat_text.return_value = json.dumps(
        {
            "title": "Viral Hook",
            "description": "Short caption #shorts",
            "tags": ["shorts"],
            "thumbnail_second": 5.0,
        }
    )
    generate_metadata(client, config, segments, "short_form", info)
    prompt = client.chat_text.call_args[0][0]
    assert "pt-br" in prompt.lower()
    assert "shorts" in prompt.lower()


def test_suggest_publish_field_title_only():
    config = load_config()
    info = VideoInfo(path="/tmp/v.mp4", duration=120.0, width=1920, height=1080, fps=30.0)
    segments = [{"text": "Clutch no final da partida"}]
    client = MagicMock()
    client.is_available.return_value = True
    client.chat_text.return_value = json.dumps({"title": "Clutch Insano"})
    result = suggest_publish_field(
        "title", client=client, config=config, segments=segments, platform="youtube", info=info
    )
    assert result["title"] == "Clutch Insano"
    assert "title" in client.chat_text.call_args[0][0].lower()


def test_parse_publish_context_game():
    ctx = parse_publish_context(
        {
            "content_type": "game",
            "game_name": "Elden Ring",
            "channel_info": "Canal de gameplay BR",
        }
    )
    assert ctx.content_type == "game"
    assert ctx.game_name == "Elden Ring"
    assert ctx.channel_info == "Canal de gameplay BR"


def test_parse_publish_context_other():
    ctx = parse_publish_context(
        {
            "content_type": "other",
            "video_context": "Timelapse de paisagem na Patagônia",
            "channel_info": "Canal de viagem",
        }
    )
    assert ctx.content_type == "other"
    assert "Patagônia" in ctx.video_context
    assert format_subject_context_block(ctx) == "Timelapse de paisagem na Patagônia"


def test_generate_metadata_includes_context_in_prompt():
    config = load_config()
    info = VideoInfo(path="/tmp/v.mp4", duration=60.0, width=1920, height=1080, fps=30.0)
    segments = [{"text": "Momento épico no jogo"}]
    client = MagicMock()
    client.is_available.return_value = True
    client.chat_text.return_value = json.dumps(
        {
            "title": "Clutch insano",
            "description": "Descrição\n\n#gaming",
            "tags": ["elden ring"],
            "thumbnail_second": 10.0,
        }
    )
    ctx = PublishContext(
        content_type="game",
        game_name="Elden Ring",
        channel_info="Canal casual de gameplay",
    )
    generate_metadata(client, config, segments, "youtube", info, context=ctx)
    prompt = client.chat_text.call_args[0][0]
    assert "Elden Ring" in prompt
    assert "Canal casual de gameplay" in prompt


def test_prompts_require_pt_br():
    config = load_config()
    from reels.config import prompts_path

    for name in ("publish_youtube.txt", "publish_short_form.txt"):
        text = prompts_path(config, name).read_text(encoding="utf-8")
        assert "PT-BR" in text or "pt-br" in text.lower()
        assert "{channel_info}" in text
        assert "{subject_context}" in text


def test_slug_from_path():
    assert slug_from_path("/tmp/My Cool Clip!.mp4", 1).startswith("01_")


def test_target_dimensions_vertical():
    info = VideoInfo(path="/x.mp4", duration=10, width=1080, height=1920, fps=30)
    w, h = target_dimensions(info, "youtube")
    assert h > w


def test_wrap_title_lines():
    title = "This is a very long title that should wrap across multiple lines nicely"
    wrapped = wrap_title_lines(title, max_chars=20, max_lines=3)
    assert "\n" in wrapped
    assert len(wrapped.split("\n")) <= 3


@patch("reels.thumbnail.subprocess.run")
def test_overlay_title_produces_jpeg(mock_run, tmp_path):
    from reels.thumbnail import overlay_title_on_image

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"x" * 200)
    out = tmp_path / "thumb.jpg"

    def fake_run(cmd, **kwargs):
        out.write_bytes(b"\xff\xd8\xff" + b"y" * 300)
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = fake_run
    config = load_config()
    overlay_title_on_image(
        frame,
        "Test Title",
        out,
        config=config,
        platform="youtube",
        work_dir=tmp_path,
        frame_height=720,
    )
    assert out.is_file()
    assert out.stat().st_size > 0


def test_api_get_publish_after_fake_job(client, tmp_path):
    out = tmp_path / "publish-out"
    publish_root = out / "publish"
    slug = slug_from_path("clip_a.mp4", 0)
    item_dir = publish_root / slug
    item_dir.mkdir(parents=True)
    thumb = item_dir / "thumbnail.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"z" * 100)
    item = PublishItem(
        video_path=str(tmp_path / "clip_a.mp4"),
        source_label="clip_a.mp4",
        platform="youtube",
        title="My Title",
        description="My description",
        tags=["tag1"],
        thumbnail_timestamp=12.0,
        thumbnail_path=str(thumb),
    )
    write_publish(
        publish_root / "manifest.json",
        PublishDocument(platform="youtube", items=[item]),
    )

    import reels.jobs as jobs_mod

    job_id = "publish-api-job"
    jobs_mod.get_job_manager()._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(tmp_path / "clip_a.mp4"),
        output_dir=str(out),
        feature="publish",
    )
    jobs_mod.get_job_manager()._running = False

    r = client.get(f"/api/jobs/{job_id}/publish")
    assert r.status_code == 200
    data = r.json()
    assert data["platform"] == "youtube"
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "My Title"
    assert data["items"][0]["thumbnail_url"] == f"/api/jobs/{job_id}/publish/0/thumbnail"

    thumb_r = client.get(f"/api/jobs/{job_id}/publish/0/thumbnail")
    assert thumb_r.status_code == 200
    assert thumb_r.headers.get("content-type", "").startswith("image/")


def test_manifest_two_videos(client, tmp_path):
    publish_root = tmp_path / "out" / "publish"
    items = []
    for i, name in enumerate(("a.mp4", "b.mp4")):
        slug = slug_from_path(name, i)
        item_dir = publish_root / slug
        item_dir.mkdir(parents=True)
        thumb = item_dir / "thumbnail.jpg"
        thumb.write_bytes(b"\xff\xd8\xff")
        item = PublishItem(
            video_path=str(tmp_path / name),
            source_label=name,
            platform="short_form",
            title=f"Title {i}",
            description=f"Desc {i}",
            tags=["viral"],
            thumbnail_timestamp=float(i),
            thumbnail_path=str(thumb),
        )
        items.append(item)
    write_publish(publish_root / "manifest.json", PublishDocument(platform="short_form", items=items))

    doc = load_publish(publish_root / "manifest.json")
    assert len(doc.items) == 2
    assert doc.platform == "short_form"
