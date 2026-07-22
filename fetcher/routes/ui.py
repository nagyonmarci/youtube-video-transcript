"""UI data endpoints — channel list, video list, admin stats."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException

import config
from db import get_pg_pool
from pg_client import _normalize_row, _normalize_rows
from worker_state import directus

logger = logging.getLogger(__name__)
router = APIRouter()

UI_PAGE_SIZE = 100
UI_CHANNEL_UPDATE_FIELDS = {"name", "topic", "channel_url", "channel_handle", "status", "video_count", "error_message", "last_refreshed"}
UI_VIDEO_UPDATE_FIELDS = {
    "quick_summary",
    "summary",
    "topics",
    "takeaways",
    "questions",
    "obsidian_note",
    "study_guide",
    "critique",
    "transcript",
    "transcript_timed",
    "ai_notes_status",
    "ai_notes_error",
}
NOT_MEMBERS_ONLY = "is_members_only IS NOT TRUE"

_SORT_COLUMNS = {"title", "uploaded_at", "duration_seconds", "status"}  # matches VideoTable.tsx's handleHeaderClick fields

_VIDEO_SELECT_COLUMNS = """
    v.id, v.video_id, v.title, v.url, v.thumbnail_url, v.uploaded_at, v.duration_seconds,
    v.status, v.is_members_only, v.transcript, v.transcript_timed, v.whisper_status,
    v.quick_summary, v.quick_summary_model, v.quick_summary_generated_at,
    v.summary, v.topics, v.takeaways, v.questions, v.obsidian_note, v.study_guide, v.critique,
    v.ai_notes_status, v.ai_notes_generated_at, v.ai_notes_error,
    CASE WHEN c.id IS NULL THEN NULL ELSE
      json_build_object('id', c.id, 'name', c.name, 'channel_handle', c.channel_handle)
    END AS channel_id
"""
_VIDEO_FROM = "FROM videos v LEFT JOIN channels c ON v.channel_id = c.id"


def build_video_where(
    search: str,
    status_filter: str,
    ai_filter: str,
    members_filter: str,
    search_transcript: bool = False,
    search_channel_ids: Optional[list] = None,
) -> tuple:
    """Parameterized WHERE-clause builder — replaces the old Directus filter[_and]/[_or] DSL."""
    clauses: list = []
    params: list = []

    def bind(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if search:
        or_parts = [f"v.title ILIKE {bind(f'%{search}%')}"]
        if search_transcript:
            or_parts.append(f"v.transcript ILIKE {bind(f'%{search}%')}")
        if search_channel_ids:
            or_parts.append(f"v.channel_id = ANY({bind(search_channel_ids)}::uuid[])")
        clauses.append("(" + " OR ".join(or_parts) + ")")
    if status_filter and status_filter != "all":
        clauses.append(f"v.status = {bind(status_filter)}")
    if ai_filter == "done":
        clauses.append(f"v.ai_notes_status = {bind('done')}")
    elif ai_filter == "missing":
        clauses.append("v.transcript IS NOT NULL AND v.transcript <> ''")
        clauses.append("v.summary IS NULL")
    elif ai_filter == "error":
        clauses.append(f"v.ai_notes_status = {bind('error')}")
    if members_filter == "hide":
        clauses.append("v.is_members_only IS NOT TRUE")
    elif members_filter == "only":
        clauses.append("v.is_members_only IS TRUE")

    return (" AND ".join(clauses) if clauses else "TRUE"), params


def build_sort(sort: str) -> str:
    sort = (sort or "").strip()
    desc = sort.startswith("-")
    column = sort.lstrip("-") or "uploaded_at"
    if column not in _SORT_COLUMNS:
        column, desc = "uploaded_at", True
    return f"v.{column} {'DESC' if desc else 'ASC'}"


@router.get("/ui/channels")
async def ui_channels():
    pool = await get_pg_pool()
    channels = _normalize_rows(await pool.fetch(
        "SELECT id, name, topic, channel_url, channel_handle, added_at, status, "
        "video_count, error_message, last_refreshed FROM channels ORDER BY added_at DESC"
    ))
    count_rows = await pool.fetch(
        f"SELECT channel_id, COUNT(*) AS count FROM videos "
        f"WHERE channel_id IS NOT NULL AND {NOT_MEMBERS_ONLY} GROUP BY channel_id"
    )
    counts = {str(row["channel_id"]): row["count"] for row in count_rows}
    return [{**ch, "video_count": counts.get(ch["id"], 0)} for ch in channels]


@router.patch("/ui/channels/{channel_id}")
async def ui_update_channel(channel_id: str, data: dict):
    update = {key: value for key, value in data.items() if key in UI_CHANNEL_UPDATE_FIELDS}
    if not update:
        raise HTTPException(status_code=400, detail="No supported channel fields")
    return await directus.update_channel(channel_id, update)


@router.delete("/ui/channels/{channel_id}")
async def ui_delete_channel(channel_id: str):
    await directus.delete_channel(channel_id)
    return {"deleted": True, "id": channel_id}


@router.get("/ui/videos")
async def ui_videos(
    channel_id: Optional[str] = None,
    sort: str = "-uploaded_at",
    page: int = 1,
    search: str = "",
    status_filter: str = "all",
    ai_filter: str = "all",
    members_filter: str = "hide",
):
    page = max(1, page)
    where, params = build_video_where(search, status_filter, ai_filter, members_filter)
    if channel_id:
        where += f" AND v.channel_id = ${len(params) + 1}"
        params.append(channel_id)
    pool = await get_pg_pool()
    total = await pool.fetchval(f"SELECT COUNT(*) FROM videos v WHERE {where}", *params)
    rows = await pool.fetch(
        f"""
        SELECT {_VIDEO_SELECT_COLUMNS} {_VIDEO_FROM}
        WHERE {where}
        ORDER BY {build_sort(sort)}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params, UI_PAGE_SIZE, (page - 1) * UI_PAGE_SIZE,
    )
    return {"items": _normalize_rows(rows), "total": total}


@router.get("/ui/search")
async def ui_search(
    q: str = "",
    page: int = 1,
    status_filter: str = "all",
    ai_filter: str = "all",
    members_filter: str = "hide",
):
    q = q.strip()
    if not q:
        return {"items": [], "total": 0}
    page = max(1, page)
    pool = await get_pg_pool()
    channel_id_rows = await pool.fetch("SELECT id FROM channels WHERE name ILIKE $1", f"%{q}%")
    channel_ids = [str(r["id"]) for r in channel_id_rows]
    where, params = build_video_where(
        q, status_filter, ai_filter, members_filter,
        search_transcript=True, search_channel_ids=channel_ids,
    )
    total = await pool.fetchval(f"SELECT COUNT(*) FROM videos v WHERE {where}", *params)
    rows = await pool.fetch(
        f"""
        SELECT {_VIDEO_SELECT_COLUMNS} {_VIDEO_FROM}
        WHERE {where}
        ORDER BY v.uploaded_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params, UI_PAGE_SIZE, (page - 1) * UI_PAGE_SIZE,
    )
    return {"items": _normalize_rows(rows), "total": total}


@router.get("/ui/videos/range")
async def ui_videos_range(date_from: str, date_to: str, tz: str = "Europe/Budapest"):
    try:
        local_tz = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, KeyError):
        local_tz = timezone.utc
    fy, fm, fd = (int(x) for x in date_from.split("-"))
    ty, tm, td = (int(x) for x in date_to.split("-"))
    start = datetime(fy, fm, fd, tzinfo=local_tz).astimezone(timezone.utc)
    end = (datetime(ty, tm, td, tzinfo=local_tz) + timedelta(days=1)).astimezone(timezone.utc)
    pool = await get_pg_pool()
    rows = await pool.fetch(
        f"""
        SELECT {_VIDEO_SELECT_COLUMNS} {_VIDEO_FROM}
        WHERE v.uploaded_at >= $1 AND v.uploaded_at < $2 AND {NOT_MEMBERS_ONLY}
        ORDER BY v.uploaded_at DESC
        """,
        start, end,
    )
    return _normalize_rows(rows)


@router.get("/ui/videos/count")
async def ui_video_count():
    pool = await get_pg_pool()
    count = await pool.fetchval(f"SELECT COUNT(*) FROM videos WHERE {NOT_MEMBERS_ONLY}")
    return {"count": count}


@router.get("/ui/admin-stats")
async def ui_admin_stats():
    local_tz = config.get_scheduler_timezone()
    local_start = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start.astimezone(timezone.utc)
    end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    pool = await get_pg_pool()
    row = await pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE {NOT_MEMBERS_ONLY}) AS total,
          COUNT(*) FILTER (WHERE {NOT_MEMBERS_ONLY} AND uploaded_at >= $1 AND uploaded_at < $2) AS today,
          COUNT(*) FILTER (WHERE {NOT_MEMBERS_ONLY} AND status = 'error') AS errors,
          COUNT(*) FILTER (WHERE {NOT_MEMBERS_ONLY} AND (transcript IS NULL OR status IN ('pending', 'no_transcript', 'error'))) AS missing_transcripts,
          COUNT(*) FILTER (WHERE {NOT_MEMBERS_ONLY} AND transcript IS NOT NULL AND transcript <> '' AND (summary IS NULL OR critique IS NULL)) AS missing_ai
        FROM videos
        """,
        start, end,
    )
    return {
        "totalVideos": row["total"],
        "todayVideos": row["today"],
        "errorVideos": row["errors"],
        "missingTranscripts": row["missing_transcripts"],
        "missingAiNotes": row["missing_ai"],
    }


@router.get("/ui/channel-coverage")
async def ui_channel_coverage():
    pool = await get_pg_pool()
    base = f"SELECT channel_id, COUNT(*) AS count FROM videos WHERE channel_id IS NOT NULL AND {NOT_MEMBERS_ONLY}"
    total, transcript_done, ai_done = await asyncio.gather(
        pool.fetch(f"{base} GROUP BY channel_id"),
        pool.fetch(f"{base} AND status = 'done' GROUP BY channel_id"),
        pool.fetch(f"{base} AND ai_notes_status = 'done' GROUP BY channel_id"),
    )

    def as_directus_shape(rows):
        return [{"channel_id": str(row["channel_id"]), "count": {"id": row["count"]}} for row in rows]

    return {
        "total": as_directus_shape(total),
        "transcriptDone": as_directus_shape(transcript_done),
        "aiDone": as_directus_shape(ai_done),
    }


@router.get("/ui/monthly-video-counts")
async def ui_monthly_video_counts():
    cutoff = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = cutoff.month - 11
    year = cutoff.year
    while month <= 0:
        month += 12
        year -= 1
    cutoff = cutoff.replace(year=year, month=month)
    pool = await get_pg_pool()
    rows = await pool.fetch(
        f"""
        SELECT to_char(date_trunc('month', uploaded_at), 'YYYY-MM') AS month, COUNT(*) AS count
        FROM videos WHERE uploaded_at >= $1 AND {NOT_MEMBERS_ONLY}
        GROUP BY 1
        """,
        cutoff,
    )
    counts = {row["month"]: row["count"] for row in rows}
    result = []
    year, month = cutoff.year, cutoff.month
    for _ in range(12):
        key = f"{year}-{month:02d}"
        result.append({"month": key, "count": counts.get(key, 0)})
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


@router.get("/ui/error-videos")
async def ui_error_videos():
    pool = await get_pg_pool()
    rows = await pool.fetch(
        """
        SELECT v.id, v.video_id, v.title, v.url,
          CASE WHEN c.id IS NULL THEN NULL ELSE
            json_build_object('name', c.name, 'channel_handle', c.channel_handle)
          END AS channel_id
        FROM videos v LEFT JOIN channels c ON v.channel_id = c.id
        WHERE v.status = 'error'
        ORDER BY v.processed_at DESC
        LIMIT 50
        """
    )
    return _normalize_rows(rows)


@router.patch("/ui/videos/{video_id}")
async def ui_update_video(video_id: str, data: dict):
    update = {key: value for key, value in data.items() if key in UI_VIDEO_UPDATE_FIELDS}
    if not update:
        raise HTTPException(status_code=400, detail="No supported video fields")
    return await directus.update_video(video_id, update)


@router.get("/ui/channels/{channel_id}/videos")
async def ui_channel_videos(channel_id: str, sort: str = "-uploaded_at"):
    pool = await get_pg_pool()
    rows = await pool.fetch(
        f"""
        SELECT {_VIDEO_SELECT_COLUMNS} {_VIDEO_FROM}
        WHERE v.channel_id = $1
        ORDER BY {build_sort(sort)}
        """,
        channel_id,
    )
    return _normalize_rows(rows)
