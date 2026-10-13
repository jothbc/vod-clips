"""One-shot migration: backfill the videos DB from existing temp/video folders.

Usage:
    python -m reels.db.migrate_filesystem

Idempotent. Registers one row per VOD and per clip, keyed by slug, and records
each legacy id (slug, ``parent::clip_slug``) as an alias so old links resolve.
"""

from __future__ import annotations

from reels.db import init_db
from reels.video_store import sync_from_filesystem


def main() -> None:
    init_db()
    result = sync_from_filesystem()
    print(
        f"Migrated {result['vods']} VOD(s) and {result['clips']} clip(s) "
        f"(recovered {result.get('orphans_recovered', 0)} orphan(s), "
        f"removed {result.get('orphans_removed', 0)} empty orphan dir(s))."
    )


if __name__ == "__main__":
    main()
