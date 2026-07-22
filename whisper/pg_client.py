"""asyncpg-based replacement for whisper's old Directus REST client.

Whisper is single-worker (no internal concurrency), so a tiny pool is enough.
The videos table (including whisper_status) is created/owned by the fetcher
service's schema.py — this module only reads/writes it, never creates it.
"""

import json
import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("json", schema="pg_catalog", encoder=json.dumps, decoder=json.loads)


async def get_pg_pool() -> asyncpg.Pool:
    global _pool
    if _pool:
        return _pool
    _pool = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "directus"),
        user=os.environ.get("POSTGRES_USER", "directus"),
        password=os.environ["POSTGRES_PASSWORD"],
        min_size=1,
        max_size=2,
        init=_init_connection,
    )
    return _pool


async def close_pg_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _normalize_row(row) -> Optional[dict]:
    if row is None:
        return None
    return {k: (str(v) if hasattr(v, "hex") else v) for k, v in dict(row).items()}


async def get_no_transcript_videos(limit: int = 50) -> list:
    """Videos flagged by the fetcher for whisper transcription that haven't been processed yet."""
    pool = await get_pg_pool()
    rows = await pool.fetch(
        """
        SELECT id, video_id, title, url, duration_seconds FROM videos
        WHERE status = 'no_transcript' AND whisper_status IS NULL AND for_whisper IS TRUE
        ORDER BY processed_at LIMIT $1
        """,
        limit,
    )
    return [_normalize_row(r) for r in rows]


async def mark_members_only_videos() -> int:
    """Bulk-mark no_transcript videos with 'MEMBERS' in the title — a redundant but
    harmless fallback now that the fetcher's for_whisper flag already excludes
    members-only videos more reliably (via the actual is_members_only field)."""
    pool = await get_pg_pool()
    result = await pool.execute(
        """
        UPDATE videos SET whisper_status = 'members_only'
        WHERE status = 'no_transcript' AND whisper_status IS NULL AND title LIKE '%MEMBERS%'
        """
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def reset_stale_processing() -> int:
    pool = await get_pg_pool()
    result = await pool.execute("UPDATE videos SET whisper_status = NULL WHERE whisper_status = 'processing'")
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def update_video(video_id: str, data: dict) -> dict:
    if not data:
        return {}
    pool = await get_pg_pool()
    set_clauses = [f"{key} = ${i}" for i, key in enumerate(data.keys(), start=1)]
    values = list(data.values()) + [video_id]
    row = await pool.fetchrow(
        f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING *",
        *values,
    )
    return _normalize_row(row) or {}


async def find_video_by_yt_id(yt_video_id: str) -> Optional[dict]:
    pool = await get_pg_pool()
    row = await pool.fetchrow("SELECT * FROM videos WHERE video_id = $1 LIMIT 1", yt_video_id)
    return _normalize_row(row)
