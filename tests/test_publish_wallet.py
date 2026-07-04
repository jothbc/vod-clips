"""Tests for publish wallet API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import ClipMetadata, VideoMetadata
from reels.publish_wallet import get_target, load_credentials, save_credentials
import reels.publish_wallet as pw
import reels.video_store as vs


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(storage_mod, "temp_root", lambda: tmp_path / "temp")
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")
    (tmp_path / "temp").mkdir(parents=True)
    vs.videos_root().mkdir(parents=True)
    return TestClient(create_app())


def test_create_and_list_targets(client):
    r = client.post(
        "/api/v2/publish/targets",
        json={"label": "Canal principal", "platform": "youtube"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["label"] == "Canal principal"
    assert data["platform"] == "youtube"
    assert data["connected"] is False
    assert data["oauth_configured"] is False

    r2 = client.get("/api/v2/publish/targets")
    assert r2.status_code == 200
    assert len(r2.json()["targets"]) == 1


def test_update_and_delete_target(client):
    created = client.post(
        "/api/v2/publish/targets",
        json={"label": "TikTok", "platform": "tiktok"},
    ).json()
    tid = created["id"]
    r = client.patch(
        f"/api/v2/publish/targets/{tid}",
        json={"label": "TikTok pessoal", "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["label"] == "TikTok pessoal"
    assert r.json()["enabled"] is False

    r_del = client.delete(f"/api/v2/publish/targets/{tid}")
    assert r_del.status_code == 204
    assert client.get("/api/v2/publish/targets").json()["targets"] == []


def test_credentials_encrypt_roundtrip(client, monkeypatch, tmp_path):
    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")
    created = client.post(
        "/api/v2/publish/targets",
        json={"label": "YT", "platform": "youtube"},
    ).json()
    tid = created["id"]
    save_credentials(tid, access_token="secret-token", refresh_token="refresh", account_label="My Channel")
    creds = load_credentials(tid)
    assert creds is not None
    assert creds["access_token"] == "secret-token"
    assert creds["refresh_token"] == "refresh"


def test_post_publish_clip_uses_clip_file(client, monkeypatch):
    parent = "vod_pub"
    clip_slug = "clip_yt"
    vs.original_dir(parent).mkdir(parents=True)
    vs.source_path(parent).write_bytes(b"\x00" * 50)
    vs.save_metadata(
        VideoMetadata(slug=parent, title="Parent", kind="original", duration=60.0, size_bytes=50)
    )
    clip_dir = vs.clip_dir(parent, clip_slug)
    clip_dir.mkdir(parents=True)
    (clip_dir / "youtube.mp4").write_bytes(b"\x00" * 40)
    vs.save_clip_metadata(
        parent,
        ClipMetadata(
            clip_slug=clip_slug,
            parent_slug=parent,
            title="Clip",
            start=0,
            end=30,
            formats=["youtube"],
        ),
    )
    clip_id = vs.make_clip_id(parent, clip_slug)

    captured: dict = {}

    class FakeState:
        id = "job_pub"
        status = "queued"

    class FakeMgr:
        def create_job(self, req):
            captured["video_path"] = req.video_path
            captured["params"] = req.params
            return FakeState()

    monkeypatch.setattr("reels.api.videos.get_job_manager", lambda: FakeMgr())

    r = client.post(
        f"/api/v2/videos/{clip_id}/publish",
        json={"platform": "youtube", "content_type": "game", "game_name": "Test"},
    )
    assert r.status_code == 202
    assert "youtube.mp4" in captured["video_path"]
    assert captured["params"]["platform"] == "youtube"


def test_oauth_config_stored_encrypted(client, tmp_path, monkeypatch):
    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")
    r = client.post(
        "/api/v2/publish/targets",
        json={
            "label": "YT OAuth",
            "platform": "youtube",
            "config": {
                "oauth_client_id": "my-client-id.apps.googleusercontent.com",
                "oauth_client_secret": "super-secret",
                "oauth_redirect_uri": "http://127.0.0.1:8000/api/v2/publish/oauth/callback/youtube",
            },
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["oauth_configured"] is True
    assert data["config"].get("oauth_client_id") == "my-client-id.apps.googleusercontent.com"
    assert "oauth_client_secret" not in data["config"]

    raw = pw.get_target_config_raw(data["id"])
    assert raw is not None
    assert raw["oauth_client_secret"].startswith("enc:")
    assert pw._decrypt_config_secret(raw["oauth_client_secret"]) == "super-secret"


def test_auth_start_uses_wallet_oauth(client, monkeypatch, tmp_path):
    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")
    created = client.post(
        "/api/v2/publish/targets",
        json={
            "label": "YT",
            "platform": "youtube",
            "config": {
                "oauth_client_id": "cid",
                "oauth_client_secret": "csecret",
            },
        },
    ).json()
    tid = created["id"]
    r = client.get(f"/api/v2/publish/targets/{tid}/auth/start")
    assert r.status_code == 200
    assert "accounts.google.com" in r.json()["auth_url"]
    assert "client_id=cid" in r.json()["auth_url"]


def test_test_upload_youtube(client, monkeypatch, tmp_path):
    monkeypatch.setattr(pw, "wallet_db_path", lambda: tmp_path / "temp" / "publish_wallet.db")
    monkeypatch.setattr(pw, "_key_path", lambda: tmp_path / "temp" / ".publish_key")
    created = client.post(
        "/api/v2/publish/targets",
        json={
            "label": "YT",
            "platform": "youtube",
            "config": {"oauth_client_id": "cid", "oauth_client_secret": "sec"},
        },
    ).json()
    tid = created["id"]
    pw.save_credentials(tid, access_token="tok", refresh_token="ref", account_label="Ch")

    with patch("reels.api.publish_wallet.test_upload_access") as test_fn:
        test_fn.return_value = {
            "ok": True,
            "checks": [{"name": "channel", "ok": True, "detail": "Ch"}],
            "channel_title": "Ch",
            "channel_id": "abc",
        }
        r = client.post(f"/api/v2/publish/targets/{tid}/test-upload")
    assert r.status_code == 200
    assert r.json()["ok"] is True
