"""asyncpg-based replacement for the old Directus REST client.

Keeps the same class/method names/signatures the old DirectusClient had, so call
sites elsewhere in the app (fetch_tasks.py, job_ops.py, job_utils.py, ai_tasks.py,
scheduler.py, routes/*.py, workers.py) need no changes beyond the import — see
worker_state.py, which still exposes the shared instance as `directus`.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import asyncpg

from db import get_pg_pool

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Current UTC time as a native datetime — asyncpg requires this (not an ISO
    string) when binding timestamptz query parameters."""
    return datetime.now(timezone.utc)


_ACTIVE_STATUSES = ["queued", "running", "paused"]

JOB_COLUMNS = (
    "id, queue, type, label, status, sort_order, payload, dedupe_key, attempts, max_attempts, "
    "progress_current, progress_total, progress_label, locked_at, locked_by, created_at, "
    "started_at, finished_at, error_message, last_error, duration_seconds, metrics"
)

_VIDEO_NARROW_COLUMNS = (
    "id, video_id, title, url, thumbnail_url, is_members_only, uploaded_at, "
    "duration_seconds, transcript, transcript_timed"
)


def _normalize_value(value):
    if isinstance(value, UUID):
        return str(value)
    return value


def _normalize_row(row: Optional[asyncpg.Record]) -> Optional[dict]:
    """Convert an asyncpg.Record to a plain dict, stringifying UUID columns.

    asyncpg returns uuid columns as asyncpg.pgproto.pgproto.UUID (a uuid.UUID
    subclass), which plain json.dumps() (used directly by routes/status.py's SSE
    stream, bypassing FastAPI's jsonable_encoder) cannot serialize on its own.
    """
    if row is None:
        return None
    return {key: _normalize_value(value) for key, value in dict(row).items()}


def _normalize_rows(rows) -> list:
    return [_normalize_row(row) for row in rows]


class PostgresClient:
    # `data` dict keys are used as column names via plain string interpolation in
    # _insert_row/_update_row below. This is only safe because every caller passes a
    # fixed, code-defined key set (e.g. routes/ui.py's UI_VIDEO_UPDATE_FIELDS /
    # UI_CHANNEL_UPDATE_FIELDS allowlists already strip unexpected field names out of
    # request bodies before they reach this client). Never widen those allowlists with
    # raw user input.

    async def _insert_row(self, table: str, data: dict, returning: str = "*") -> dict:
        columns = list(data.keys())
        values = list(data.values())
        placeholders = ", ".join(f"${i}" for i in range(1, len(values) + 1))
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) RETURNING {returning}"
        pool = await get_pg_pool()
        row = await pool.fetchrow(query, *values)
        return _normalize_row(row)

    async def _update_row(self, table: str, row_id: str, data: dict, returning: str = "*") -> Optional[dict]:
        if not data:
            return await self._get_row(table, row_id, returning)
        set_clauses = [f"{key} = ${i}" for i, key in enumerate(data.keys(), start=1)]
        values = list(data.values()) + [row_id]
        query = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING {returning}"
        pool = await get_pg_pool()
        row = await pool.fetchrow(query, *values)
        return _normalize_row(row)

    async def _get_row(self, table: str, row_id: str, columns: str = "*") -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow(f"SELECT {columns} FROM {table} WHERE id = $1", row_id)
        return _normalize_row(row)

    # ---- App settings ----

    async def get_setting(self, key: str) -> Optional[str]:
        pool = await get_pg_pool()
        return await pool.fetchval("SELECT value FROM app_settings WHERE key = $1", key)

    async def set_setting(self, key: str, value: str) -> dict:
        pool = await get_pg_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO app_settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            RETURNING id, key, value
            """,
            key, value,
        )
        return _normalize_row(row)

    # ---- Jobs ----

    async def job_label(self, task: dict) -> str:
        task_type = task.get("type") or "job"
        if task_type in ("channel", "refresh"):
            channel = await self.get_channel(task["channel_id"]) if task.get("channel_id") else None
            name = (channel or {}).get("name") or (channel or {}).get("channel_handle") or task.get("channel_url") or task.get("channel_id") or ""
            prefix = "Csatorna letöltés" if task_type == "channel" else "Csatorna frissítés"
            return f"{prefix}: {name}".strip()
        if task_type == "video":
            return f"Videó letöltés: {task.get('video_url') or ''}".strip()
        if task_type == "refresh_dates":
            return "Hiányzó dátumok frissítése"
        if task_type == "refresh_thumbnails":
            return "Hiányzó thumbnail képek frissítése"
        if task_type == "ai_notes":
            return f"Hiányzó AI jegyzetek: {task.get('limit') or ''}".strip()
        if task_type == "ai_note_video":
            video = await self.get_video(task["video_id"]) if task.get("video_id") else None
            title = (video or {}).get("title") or (video or {}).get("video_id") or task.get("video_id") or ""
            return f"AI jegyzet: {title}".strip()
        return task_type

    async def next_job_sort_order(self, queue: str) -> int:
        pool = await get_pg_pool()
        value = await pool.fetchval(
            """
            SELECT sort_order FROM jobs
            WHERE queue = $1 AND status IN ('queued', 'paused')
            ORDER BY sort_order DESC LIMIT 1
            """,
            queue,
        )
        return (value or 0) + 1000

    async def create_job(
        self,
        queue: str,
        task: dict,
        label: Optional[str] = None,
        sort_order: Optional[int] = None,
        dedupe_key: Optional[str] = None,
        max_attempts: int = 3,
    ) -> dict:
        if dedupe_key:
            existing = await self.get_active_job_by_dedupe_key(queue, dedupe_key)
            if existing:
                return {**existing, "existing": True}
        if sort_order is None:
            sort_order = await self.next_job_sort_order(queue)
        resolved_label = label or await self.job_label(task)
        pool = await get_pg_pool()
        try:
            row = await pool.fetchrow(
                f"""
                INSERT INTO jobs (queue, type, label, status, sort_order, payload, dedupe_key, attempts, max_attempts)
                VALUES ($1, $2, $3, 'queued', $4, $5, $6, 0, $7)
                RETURNING {JOB_COLUMNS}
                """,
                queue, task.get("type"), resolved_label, sort_order, task, dedupe_key, max_attempts,
            )
        except asyncpg.UniqueViolationError:
            # Raced against another create_job() with the same dedupe_key — the partial
            # unique index (idx_jobs_dedupe_active) rejected our insert.
            if dedupe_key:
                existing = await self.get_active_job_by_dedupe_key(queue, dedupe_key)
                if existing:
                    return {**existing, "existing": True}
            raise
        return _normalize_row(row)

    async def get_job(self, job_id: str) -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow(f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = $1", job_id)
        return _normalize_row(row)

    async def list_jobs(self, statuses: Optional[list] = None, limit: int = 200) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch(
            f"""
            SELECT {JOB_COLUMNS} FROM jobs
            WHERE $1::text[] IS NULL OR status = ANY($1::text[])
            ORDER BY queue, sort_order, created_at
            LIMIT $2
            """,
            statuses, limit,
        )
        return _normalize_rows(rows)

    async def count_jobs(self, queue: str, statuses: str = "queued") -> int:
        status_list = [s.strip() for s in statuses.split(",") if s.strip()]
        pool = await get_pg_pool()
        return await pool.fetchval(
            "SELECT COUNT(*) FROM jobs WHERE queue = $1 AND status = ANY($2::text[])",
            queue, status_list,
        )

    async def get_running_job(self, queue: str) -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow(
            f"SELECT {JOB_COLUMNS} FROM jobs WHERE queue = $1 AND status = 'running' ORDER BY started_at LIMIT 1",
            queue,
        )
        return _normalize_row(row)

    async def get_ai_note_job_video_ids(self) -> set:
        pool = await get_pg_pool()
        rows = await pool.fetch(
            """
            SELECT payload ->> 'video_id' AS video_id FROM jobs
            WHERE queue = 'ai' AND type = 'ai_note_video' AND status = ANY($1::text[])
              AND payload ->> 'video_id' IS NOT NULL
            """,
            _ACTIVE_STATUSES,
        )
        return {row["video_id"] for row in rows}

    async def get_active_job_by_type(self, queue: str, job_type: str) -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow(
            f"""
            SELECT {JOB_COLUMNS} FROM jobs
            WHERE queue = $1 AND type = $2 AND status = ANY($3::text[])
            ORDER BY created_at LIMIT 1
            """,
            queue, job_type, _ACTIVE_STATUSES,
        )
        return _normalize_row(row)

    async def get_active_job_by_dedupe_key(self, queue: str, dedupe_key: str) -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow(
            f"""
            SELECT {JOB_COLUMNS} FROM jobs
            WHERE queue = $1 AND dedupe_key = $2 AND status = ANY($3::text[])
            ORDER BY created_at LIMIT 1
            """,
            queue, dedupe_key, _ACTIVE_STATUSES,
        )
        return _normalize_row(row)

    async def update_job(self, job_id: str, data: dict) -> dict:
        return await self._update_row("jobs", job_id, data, returning=JOB_COLUMNS) or {}

    async def delete_job(self, job_id: str) -> None:
        pool = await get_pg_pool()
        await pool.execute("DELETE FROM jobs WHERE id = $1", job_id)

    async def delete_old_jobs(self, older_than_days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        pool = await get_pg_pool()
        result = await pool.execute(
            "DELETE FROM jobs WHERE status IN ('done', 'cancelled') AND created_at < $1",
            cutoff,
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    # ---- Channel CRUD ----

    async def create_channel(self, data: dict) -> dict:
        return await self._insert_row("channels", data)

    async def get_channel(self, channel_id: str) -> Optional[dict]:
        return await self._get_row("channels", channel_id)

    async def get_all_channels(self) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch("SELECT * FROM channels ORDER BY added_at")
        return _normalize_rows(rows)

    async def get_channels_by_status(self, status: str) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch("SELECT * FROM channels WHERE status = $1", status)
        return _normalize_rows(rows)

    async def update_channel(self, channel_id: str, data: dict) -> dict:
        return await self._update_row("channels", channel_id, data) or {}

    async def delete_channel(self, channel_id: str) -> None:
        pool = await get_pg_pool()
        await pool.execute("DELETE FROM channels WHERE id = $1", channel_id)  # ON DELETE CASCADE removes its videos

    async def find_channel_by_handle(self, handle: str) -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow("SELECT * FROM channels WHERE channel_handle = $1 LIMIT 1", handle)
        return _normalize_row(row)

    # ---- Video CRUD ----

    async def create_video(self, data: dict) -> dict:
        return await self._insert_row("videos", data)

    async def update_video(self, video_id: str, data: dict) -> dict:
        return await self._update_row("videos", video_id, data) or {}

    async def get_video(self, video_id: str) -> Optional[dict]:
        # Narrow column list — matches the old DirectusClient.get_video()'s explicit
        # `fields=` list; callers (routes/ai.py, ai_tasks.py) only read these fields.
        return await self._get_row("videos", video_id, _VIDEO_NARROW_COLUMNS)

    async def get_videos_by_channel(self, channel_id: str) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch(
            "SELECT id, video_id, title, uploaded_at, thumbnail_url, is_members_only, status "
            "FROM videos WHERE channel_id = $1",
            channel_id,
        )
        return _normalize_rows(rows)

    async def get_videos_missing_date(self) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch("SELECT id, video_id FROM videos WHERE uploaded_at IS NULL")
        return _normalize_rows(rows)

    async def get_videos_missing_thumbnail(self) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch("SELECT id, video_id FROM videos WHERE thumbnail_url IS NULL")
        return _normalize_rows(rows)

    @staticmethod
    def _missing_ai_notes_where(year: Optional[int] = None) -> tuple:
        clauses = [
            "transcript IS NOT NULL AND transcript <> ''",
            "(summary IS NULL OR critique IS NULL OR ai_notes_status = 'error')",
        ]
        params: list = []
        if year:
            params = [datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year + 1, 1, 1, tzinfo=timezone.utc)]
            clauses.append("uploaded_at >= $1 AND uploaded_at < $2")
        return " AND ".join(clauses), params

    async def get_videos_missing_ai_notes(self, limit: int = 10, year: Optional[int] = None) -> list:
        where, params = self._missing_ai_notes_where(year)
        pool = await get_pg_pool()
        rows = await pool.fetch(
            f"""
            SELECT id, video_id, title, url, uploaded_at, duration_seconds, transcript, transcript_timed
            FROM videos WHERE {where}
            ORDER BY uploaded_at DESC LIMIT ${len(params) + 1}
            """,
            *params, limit,
        )
        return _normalize_rows(rows)

    async def count_videos_missing_ai_notes(self, year: Optional[int] = None) -> int:
        where, params = self._missing_ai_notes_where(year)
        pool = await get_pg_pool()
        return await pool.fetchval(f"SELECT COUNT(*) FROM videos WHERE {where}", *params)

    async def get_channel_videos_missing_ai_notes(self, channel_id: str, limit: int = 500) -> list:
        where, params = self._missing_ai_notes_where()
        pool = await get_pg_pool()
        rows = await pool.fetch(
            f"""
            SELECT id, video_id, title, url, uploaded_at, duration_seconds, transcript, transcript_timed
            FROM videos WHERE channel_id = $1 AND {where}
            ORDER BY uploaded_at DESC LIMIT ${len(params) + 2}
            """,
            channel_id, *params, limit,
        )
        return _normalize_rows(rows)

    async def get_videos_with_ai_status(self, status: str) -> list:
        pool = await get_pg_pool()
        rows = await pool.fetch(
            "SELECT id, video_id, title, ai_notes_status FROM videos WHERE ai_notes_status = $1",
            status,
        )
        return _normalize_rows(rows)

    async def find_video_by_yt_id(self, yt_video_id: str) -> Optional[dict]:
        pool = await get_pg_pool()
        row = await pool.fetchrow("SELECT * FROM videos WHERE video_id = $1 LIMIT 1", yt_video_id)
        return _normalize_row(row)
