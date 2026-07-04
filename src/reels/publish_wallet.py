"""SQLite wallet for publish targets and encrypted OAuth credentials."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from reels.storage import temp_root

PublishPlatform = Literal["youtube", "instagram", "tiktok"]


class YouTubeTargetConfig(BaseModel):
    category_id: str = "20"
    privacy: Literal["public", "unlisted", "private"] = "unlisted"
    default_language: str = "pt"
    made_for_kids: bool = False
    default_tags: list[str] = Field(default_factory=list)


class TikTokTargetConfig(BaseModel):
    privacy_level: str = "PUBLIC_TO_EVERYONE"
    disable_comment: bool = False
    disable_duet: bool = False


class InstagramTargetConfig(BaseModel):
    ig_user_id: str = ""
    share_to_feed: bool = True


class PublishTarget(BaseModel):
    id: str
    label: str
    platform: PublishPlatform
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    connected: bool = False
    oauth_configured: bool = False
    account_label: str = ""
    account_id: str = ""
    created_at: str = ""
    updated_at: str = ""


OAUTH_CLIENT_ID_KEY = "oauth_client_id"
OAUTH_CLIENT_SECRET_KEY = "oauth_client_secret"
OAUTH_REDIRECT_KEY = "oauth_redirect_uri"
_ENCRYPTED_PREFIX = "enc:"

DEFAULT_OAUTH_REDIRECT: dict[PublishPlatform, str] = {
    "youtube": "http://127.0.0.1:8000/api/v2/publish/oauth/callback/youtube",
    "tiktok": "http://127.0.0.1:8000/api/v2/publish/oauth/callback/tiktok",
    "instagram": "http://127.0.0.1:8000/api/v2/publish/oauth/callback/instagram",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def wallet_db_path() -> Path:
    return temp_root() / "publish_wallet.db"


def _key_path() -> Path:
    return temp_root() / ".publish_key"


def _fernet():
    from cryptography.fernet import Fernet

    key_path = _key_path()
    env_key = os.environ.get("REELS_PUBLISH_KEY")
    if env_key:
        return Fernet(env_key.encode() if isinstance(env_key, str) else env_key)
    if key_path.is_file():
        key = key_path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
    return Fernet(key)


def _encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode()).decode()


def _encrypt_config_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_ENCRYPTED_PREFIX):
        return value
    return f"{_ENCRYPTED_PREFIX}{_encrypt(value)}"


def _decrypt_config_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_ENCRYPTED_PREFIX):
        return _decrypt(value[len(_ENCRYPTED_PREFIX) :])
    return value


def _has_oauth_app_config(config: dict[str, Any]) -> bool:
    client_id = str(config.get(OAUTH_CLIENT_ID_KEY, "")).strip()
    secret = _decrypt_config_secret(str(config.get(OAUTH_CLIENT_SECRET_KEY, "")))
    return bool(client_id and secret)


def public_target_config(config: dict[str, Any]) -> dict[str, Any]:
    public = dict(config)
    public.pop(OAUTH_CLIENT_SECRET_KEY, None)
    return public


def prepare_target_config(
    platform: PublishPlatform,
    config: dict[str, Any] | None,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(existing or _default_config(platform))
    incoming = dict(config or {})
    for key, value in incoming.items():
        if key == OAUTH_CLIENT_SECRET_KEY:
            continue
        base[key] = value
    secret_in = str(incoming.get(OAUTH_CLIENT_SECRET_KEY, "")).strip()
    if secret_in:
        base[OAUTH_CLIENT_SECRET_KEY] = _encrypt_config_secret(secret_in)
    elif existing and existing.get(OAUTH_CLIENT_SECRET_KEY):
        base[OAUTH_CLIENT_SECRET_KEY] = existing[OAUTH_CLIENT_SECRET_KEY]
    else:
        base.pop(OAUTH_CLIENT_SECRET_KEY, None)
    if not str(base.get(OAUTH_REDIRECT_KEY, "")).strip():
        base[OAUTH_REDIRECT_KEY] = DEFAULT_OAUTH_REDIRECT[platform]
    return base


def get_target_config_raw(target_id: str) -> dict[str, Any] | None:
    init_wallet_db()
    with _conn() as con:
        row = con.execute("SELECT config_json FROM publish_targets WHERE id = ?", (target_id,)).fetchone()
        if not row:
            return None
        return json.loads(row["config_json"] or "{}")


def get_target_oauth_credentials(target: PublishTarget) -> dict[str, str]:
    raw = get_target_config_raw(target.id) or {}
    client_id = str(raw.get(OAUTH_CLIENT_ID_KEY, "")).strip()
    client_secret = _decrypt_config_secret(str(raw.get(OAUTH_CLIENT_SECRET_KEY, "")))
    redirect_uri = str(raw.get(OAUTH_REDIRECT_KEY, "")).strip() or DEFAULT_OAUTH_REDIRECT[target.platform]
    env_map: dict[PublishPlatform, tuple[str, str, str]] = {
        "youtube": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "OAUTH_REDIRECT_URI"),
        "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_OAUTH_REDIRECT_URI"),
        "instagram": ("META_APP_ID", "META_APP_SECRET", "META_OAUTH_REDIRECT_URI"),
    }
    env_id, env_secret, env_redirect = env_map[target.platform]
    if not client_id:
        client_id = os.environ.get(env_id, "").strip()
    if not client_secret:
        client_secret = os.environ.get(env_secret, "").strip()
    if not redirect_uri:
        redirect_uri = os.environ.get(env_redirect, DEFAULT_OAUTH_REDIRECT[target.platform])
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


@contextmanager
def _conn():
    path = wallet_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_wallet_db() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS publish_targets (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                platform TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publish_credentials (
                target_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL DEFAULT '',
                refresh_token TEXT NOT NULL DEFAULT '',
                expires_at TEXT,
                scopes TEXT NOT NULL DEFAULT '',
                account_label TEXT NOT NULL DEFAULT '',
                account_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (target_id) REFERENCES publish_targets(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS publish_history (
                id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL,
                video_id TEXT NOT NULL DEFAULT '',
                job_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                platform_post_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (target_id) REFERENCES publish_targets(id) ON DELETE CASCADE
            );
            """
        )


def _default_config(platform: PublishPlatform) -> dict[str, Any]:
    if platform == "youtube":
        return YouTubeTargetConfig().model_dump()
    if platform == "tiktok":
        return TikTokTargetConfig().model_dump()
    return InstagramTargetConfig().model_dump()


def _row_to_target(row: sqlite3.Row, cred: sqlite3.Row | None) -> PublishTarget:
    raw_config = json.loads(row["config_json"] or "{}")
    return PublishTarget(
        id=row["id"],
        label=row["label"],
        platform=row["platform"],  # type: ignore[arg-type]
        enabled=bool(row["enabled"]),
        config=public_target_config(raw_config),
        connected=cred is not None and bool(cred["access_token"]),
        oauth_configured=_has_oauth_app_config(raw_config),
        account_label=cred["account_label"] if cred else "",
        account_id=cred["account_id"] if cred else "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_targets() -> list[PublishTarget]:
    init_wallet_db()
    with _conn() as con:
        rows = con.execute("SELECT * FROM publish_targets ORDER BY created_at").fetchall()
        out: list[PublishTarget] = []
        for row in rows:
            cred = con.execute(
                "SELECT * FROM publish_credentials WHERE target_id = ?", (row["id"],)
            ).fetchone()
            out.append(_row_to_target(row, cred))
        return out


def get_target(target_id: str) -> PublishTarget | None:
    init_wallet_db()
    with _conn() as con:
        row = con.execute("SELECT * FROM publish_targets WHERE id = ?", (target_id,)).fetchone()
        if not row:
            return None
        cred = con.execute(
            "SELECT * FROM publish_credentials WHERE target_id = ?", (target_id,)
        ).fetchone()
        return _row_to_target(row, cred)


def create_target(
    *,
    label: str,
    platform: PublishPlatform,
    config: dict[str, Any] | None = None,
) -> PublishTarget:
    init_wallet_db()
    tid = uuid.uuid4().hex
    now = _utc_now()
    cfg = prepare_target_config(platform, config)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO publish_targets (id, label, platform, enabled, config_json, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (tid, label, platform, json.dumps(cfg), now, now),
        )
    target = get_target(tid)
    assert target is not None
    return target


def update_target(
    target_id: str,
    *,
    label: str | None = None,
    enabled: bool | None = None,
    config: dict[str, Any] | None = None,
) -> PublishTarget:
    init_wallet_db()
    existing = get_target(target_id)
    if not existing:
        raise ValueError("Target not found")
    raw_existing = get_target_config_raw(target_id) or {}
    now = _utc_now()
    new_label = label if label is not None else existing.label
    new_enabled = enabled if enabled is not None else existing.enabled
    if config is not None:
        new_config = prepare_target_config(existing.platform, config, existing=raw_existing)
    else:
        new_config = raw_existing
    with _conn() as con:
        con.execute(
            """
            UPDATE publish_targets
            SET label = ?, enabled = ?, config_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_label, int(new_enabled), json.dumps(new_config), now, target_id),
        )
    updated = get_target(target_id)
    assert updated is not None
    return updated


def delete_target(target_id: str) -> None:
    init_wallet_db()
    with _conn() as con:
        con.execute("DELETE FROM publish_targets WHERE id = ?", (target_id,))


def save_credentials(
    target_id: str,
    *,
    access_token: str,
    refresh_token: str = "",
    expires_at: str | None = None,
    scopes: str = "",
    account_label: str = "",
    account_id: str = "",
) -> None:
    init_wallet_db()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO publish_credentials
            (target_id, access_token, refresh_token, expires_at, scopes, account_label, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scopes = excluded.scopes,
                account_label = excluded.account_label,
                account_id = excluded.account_id
            """,
            (
                target_id,
                _encrypt(access_token),
                _encrypt(refresh_token),
                expires_at,
                scopes,
                account_label,
                account_id,
            ),
        )


def load_credentials(target_id: str) -> dict[str, str] | None:
    init_wallet_db()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM publish_credentials WHERE target_id = ?", (target_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "access_token": _decrypt(row["access_token"]),
            "refresh_token": _decrypt(row["refresh_token"]),
            "expires_at": row["expires_at"] or "",
            "scopes": row["scopes"] or "",
            "account_label": row["account_label"] or "",
            "account_id": row["account_id"] or "",
        }


def clear_credentials(target_id: str) -> None:
    init_wallet_db()
    with _conn() as con:
        con.execute("DELETE FROM publish_credentials WHERE target_id = ?", (target_id,))


def add_history(
    *,
    target_id: str,
    video_id: str,
    job_id: str,
    status: str,
    platform_post_id: str = "",
    error: str = "",
) -> str:
    init_wallet_db()
    hid = uuid.uuid4().hex
    with _conn() as con:
        con.execute(
            """
            INSERT INTO publish_history
            (id, target_id, video_id, job_id, status, platform_post_id, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hid,
                target_id,
                video_id or "",
                job_id or "",
                status,
                platform_post_id,
                error,
                _utc_now(),
            ),
        )
    return hid
