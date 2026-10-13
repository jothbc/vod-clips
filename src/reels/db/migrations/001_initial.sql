-- Initial unified schema: videos, aliases, transcripts, jobs, and publish wallet.

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    parent_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'original',
    title TEXT NOT NULL DEFAULT '',
    format TEXT,
    formats_available TEXT NOT NULL DEFAULT '[]',
    source_feature TEXT,
    start_sec REAL,
    end_sec REAL,
    duration REAL NOT NULL DEFAULT 0,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    fps REAL NOT NULL DEFAULT 0,
    codec TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source_filename TEXT NOT NULL DEFAULT '',
    webcam_region TEXT,
    published INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    storage_root TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_parent ON videos(parent_id);
CREATE INDEX IF NOT EXISTS idx_videos_slug ON videos(slug);
CREATE INDEX IF NOT EXISTS idx_videos_kind ON videos(kind);

CREATE TABLE IF NOT EXISTS video_aliases (
    alias TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_video_aliases_video ON video_aliases(video_id);

CREATE TABLE IF NOT EXISTS transcripts (
    video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    segments_json TEXT NOT NULL DEFAULT '[]',
    segments_original_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT,
    feature TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    params_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    progress_percent REAL NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    result_video_id TEXT,
    output_dir TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_feature ON jobs(status, feature);
CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(video_id, feature, params_hash, status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    phase TEXT NOT NULL DEFAULT '',
    percent REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);

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
    target_id TEXT PRIMARY KEY REFERENCES publish_targets(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL DEFAULT '',
    refresh_token TEXT NOT NULL DEFAULT '',
    expires_at TEXT,
    scopes TEXT NOT NULL DEFAULT '',
    account_label TEXT NOT NULL DEFAULT '',
    account_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS publish_history (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES publish_targets(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL DEFAULT '',
    job_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    platform_post_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_publish_history_video ON publish_history(video_id);
