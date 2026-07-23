"""Idempotent DDL bootstrap for the app's own tables (channels, videos, jobs, app_settings).

Directus's system tables (directus_collections, directus_fields, ...) are untouched by
this module and by the whole app — they are leftover Directus-internal metadata from
before the Postgres migration, deliberately left in place.

`whisper_status` lives on the videos table but is used by the separate whisper service —
this module is its single owner (whisper only reads/writes it, never creates it).
"""

import logging

from db import get_pg_pool

logger = logging.getLogger(__name__)

_CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS channels (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255),
        channel_url VARCHAR(512),
        channel_handle VARCHAR(255),
        added_at TIMESTAMPTZ DEFAULT now(),
        status VARCHAR(50) DEFAULT 'pending',
        video_count INTEGER DEFAULT 0,
        error_message TEXT,
        last_refreshed TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS videos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        video_id VARCHAR(50),
        channel_id UUID REFERENCES channels(id) ON DELETE CASCADE,
        title VARCHAR(512),
        url VARCHAR(512),
        thumbnail_url VARCHAR(1024),
        is_members_only BOOLEAN DEFAULT false,
        duration_seconds INTEGER,
        uploaded_at TIMESTAMPTZ,
        transcript TEXT,
        status VARCHAR(50) DEFAULT 'pending',
        processed_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        key VARCHAR(100) NOT NULL UNIQUE,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        queue VARCHAR(50) NOT NULL,
        type VARCHAR(100) NOT NULL,
        label VARCHAR(512),
        status VARCHAR(50) NOT NULL DEFAULT 'queued',
        sort_order INTEGER DEFAULT 0,
        payload JSON,
        created_at TIMESTAMPTZ DEFAULT now(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        error_message TEXT
    )
    """,
]

# Columns bolted on after the original tables — kept as their own ALTER statements
# (mirrors the historical AI_NOTE_FIELDS / JOB_PROGRESS_FIELDS / CHANNEL_EXTRA_FIELDS
# split in the old directus_client.py) so future columns follow the same pattern.
_ALTER_COLUMNS = [
    # channels
    "ALTER TABLE channels ADD COLUMN IF NOT EXISTS topic VARCHAR(255)",
    # videos — added over time
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS transcript_timed TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS for_whisper BOOLEAN DEFAULT false",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS topics JSON",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS takeaways JSON",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS questions JSON",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS obsidian_note TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS study_guide TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS critique TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS quick_summary TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS quick_summary_model VARCHAR(255)",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS quick_summary_generated_at TIMESTAMPTZ",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_notes_status VARCHAR(50)",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_notes_generated_at TIMESTAMPTZ",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_notes_error TEXT",
    # videos — whisper_status: owned here, whisper service no longer bootstraps it
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS whisper_status VARCHAR(50)",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS whisper_attempts INTEGER DEFAULT 0",
    # jobs — progress/lock/metrics fields
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(512)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_current INTEGER",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_total INTEGER",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_label VARCHAR(512)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_by VARCHAR(255)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duration_seconds INTEGER",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS metrics JSON",
    # id defaults — lets INSERTs omit id and rely on RETURNING id
    "ALTER TABLE channels ALTER COLUMN id SET DEFAULT gen_random_uuid()",
    "ALTER TABLE videos ALTER COLUMN id SET DEFAULT gen_random_uuid()",
    "ALTER TABLE app_settings ALTER COLUMN id SET DEFAULT gen_random_uuid()",
    "ALTER TABLE jobs ALTER COLUMN id SET DEFAULT gen_random_uuid()",
]


async def ensure_schema() -> None:
    """Create the app's own tables/columns if missing. Safe to run on every startup,
    from multiple containers concurrently (guarded by an advisory lock, same pattern
    as db.py's ensure_database_indexes())."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(hashtext('youtube_video_transcript:schema_bootstrap'))")
        try:
            for statement in _CREATE_TABLES:
                await conn.execute(statement)
            for statement in _ALTER_COLUMNS:
                try:
                    await conn.execute(statement)
                except Exception as e:
                    logger.warning(f"Could not apply schema statement '{statement}': {e}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtext('youtube_video_transcript:schema_bootstrap'))")
    logger.info("Ensured application schema (channels, videos, jobs, app_settings)")
