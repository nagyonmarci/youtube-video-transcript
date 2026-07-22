"""PostgreSQL connection pool and schema index bootstrap."""

import json
import logging
from typing import Optional

import asyncpg

import config

logger = logging.getLogger(__name__)

pg_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("json", schema="pg_catalog", encoder=json.dumps, decoder=json.loads)


async def get_pg_pool() -> asyncpg.Pool:
    global pg_pool
    if pg_pool:
        return pg_pool
    pg_pool = await asyncpg.create_pool(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        database=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
        min_size=1,
        max_size=max(4, config.FETCH_WORKER_CONCURRENCY + config.AI_WORKER_CONCURRENCY + 2),
        init=_init_connection,
    )
    return pg_pool


async def close_pg_pool():
    global pg_pool
    if pg_pool:
        await pg_pool.close()
        pg_pool = None


async def ensure_database_indexes():
    statements = [
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_by VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS idx_videos_uploaded_at ON videos (uploaded_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos (channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_videos_members_only ON videos (is_members_only)",
        "CREATE INDEX IF NOT EXISTS idx_videos_ai_notes_status ON videos (ai_notes_status)",
        "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos (status)",
        "CREATE INDEX IF NOT EXISTS idx_videos_whisper_candidates ON videos (whisper_status) WHERE status = 'no_transcript' AND for_whisper IS TRUE",
        "CREATE INDEX IF NOT EXISTS idx_videos_summary_missing ON videos (id) WHERE summary IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_videos_thumbnail_missing ON videos (id) WHERE thumbnail_url IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue_status_sort ON jobs (queue, status, sort_order, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active ON jobs (queue, dedupe_key) WHERE status IN ('queued', 'running', 'paused') AND dedupe_key IS NOT NULL",
        r"UPDATE videos SET is_members_only = true WHERE is_members_only IS NOT TRUE AND title ~* '\mmembers?\M'",
        "CREATE TABLE IF NOT EXISTS app_logs (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(), source TEXT, level TEXT, logger TEXT, message TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_app_logs_ts ON app_logs (ts DESC)",
    ]
    try:
        conn = await asyncpg.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            database=config.POSTGRES_DB,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
        )
    except Exception as e:
        logger.warning(f"Could not connect to Postgres for index bootstrap: {e}")
        return
    try:
        await conn.execute("SELECT pg_advisory_lock(hashtext('youtube_video_transcript:index_bootstrap'))")
        try:
            await conn.execute("""
                WITH ranked AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY queue, dedupe_key
                            ORDER BY
                                CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                                created_at
                        ) AS rn
                    FROM jobs
                    WHERE dedupe_key IS NOT NULL
                      AND status IN ('queued', 'running', 'paused')
                )
                UPDATE jobs
                SET
                    status = 'cancelled',
                    finished_at = NOW(),
                    error_message = 'Cancelled duplicate active job during dedupe cleanup'
                WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """)
        except Exception as e:
            logger.warning(f"Could not clean duplicate active jobs before index bootstrap: {e}")
        for statement in statements:
            try:
                await conn.execute(statement)
            except Exception as e:
                logger.warning(f"Could not ensure index with statement '{statement}': {e}")
        logger.info("Ensured database indexes")
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock(hashtext('youtube_video_transcript:index_bootstrap'))")
        except Exception:
            pass
        await conn.close()
