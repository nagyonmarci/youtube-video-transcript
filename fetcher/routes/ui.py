"""UI data endpoints — channel list, video list, admin stats."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException

import config
from worker_state import directus

logger = logging.getLogger(__name__)
router = APIRouter()

UI_PAGE_SIZE = 100
UI_VIDEO_FIELDS = ",".join([
    "id,video_id,title,url,thumbnail_url,uploaded_at,duration_seconds,status,is_members_only,transcript,transcript_timed,whisper_status",
    "quick_summary,quick_summary_model,quick_summary_generated_at",
    "summary,topics,takeaways,questions,obsidian_note,study_guide,critique,ai_notes_status,ai_notes_generated_at,ai_notes_error",
    "channel_id.id,channel_id.name,channel_id.channel_handle",
])
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
NOT_MEMBERS_ONLY = {
    "filter[_or][0][is_members_only][_neq]": "true",
    "filter[_or][1][is_members_only][_null]": "true",
}


def directus_query(path: str, params: dict) -> str:
    return f"{path}?{urlencode(params)}"


def apply_ui_video_filters(
    params: dict,
    search: str,
    status_filter: str,
    ai_filter: str,
    members_filter: str,
    search_transcript: bool = False,
    search_channel_ids: Optional[list] = None,
) -> None:
    and_index = 0

    def next_and() -> str:
        nonlocal and_index
        idx = and_index
        and_index += 1
        return f"filter[_and][{idx}]"

    if search:
        base = next_and()
        or_idx = 0
        params[f"{base}[_or][{or_idx}][title][_icontains]"] = search
        or_idx += 1
        if search_transcript:
            params[f"{base}[_or][{or_idx}][transcript][_icontains]"] = search
            or_idx += 1
        if search_channel_ids:
            params[f"{base}[_or][{or_idx}][channel_id][_in]"] = ",".join(search_channel_ids)
    if status_filter and status_filter != "all":
        params[f"{next_and()}[status][_eq]"] = status_filter
    if ai_filter == "done":
        params[f"{next_and()}[ai_notes_status][_eq]"] = "done"
    elif ai_filter == "missing":
        params[f"{next_and()}[transcript][_nnull]"] = "true"
        params[f"{next_and()}[summary][_null]"] = "true"
    elif ai_filter == "error":
        params[f"{next_and()}[ai_notes_status][_eq]"] = "error"
    if members_filter == "hide":
        base = next_and()
        params[f"{base}[_or][0][is_members_only][_neq]"] = "true"
        params[f"{base}[_or][1][is_members_only][_null]"] = "true"
    elif members_filter == "only":
        params[f"{next_and()}[is_members_only][_eq]"] = "true"


async def count_ui_videos(extra_params: Optional[dict] = None) -> int:
    params = {"limit": "1", "meta": "filter_count", "fields": "id"}
    if extra_params:
        params.update(extra_params)
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("meta", {}).get("filter_count", 0)


@router.get("/ui/channels")
async def ui_channels():
    data = await directus._request("GET", "/items/channels?sort[]=-added_at&limit=-1")
    count_params = {"aggregate[count]": "id", "groupBy[]": "channel_id", "limit": "-1", **NOT_MEMBERS_ONLY}
    count_data = await directus._request("GET", directus_query("/items/videos", count_params))
    counts = {
        row.get("channel_id"): int((row.get("count") or {}).get("id") or 0)
        for row in count_data.get("data", [])
        if row.get("channel_id")
    }
    return [
        {**channel, "video_count": counts.get(channel.get("id"), 0)}
        for channel in data.get("data", [])
    ]


@router.patch("/ui/channels/{channel_id}")
async def ui_update_channel(channel_id: str, data: dict):
    update = {key: value for key, value in data.items() if key in UI_CHANNEL_UPDATE_FIELDS}
    if not update:
        raise HTTPException(status_code=400, detail="No supported channel fields")
    return await directus.update_channel(channel_id, update)


@router.delete("/ui/channels/{channel_id}")
async def ui_delete_channel(channel_id: str):
    await directus._request("DELETE", f"/items/channels/{channel_id}")
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
    params = {
        "sort": sort,
        "limit": str(UI_PAGE_SIZE),
        "offset": str((page - 1) * UI_PAGE_SIZE),
        "meta": "filter_count",
        "fields": UI_VIDEO_FIELDS,
    }
    if channel_id:
        params["filter[channel_id][_eq]"] = channel_id
    apply_ui_video_filters(params, search, status_filter, ai_filter, members_filter)
    data = await directus._request("GET", directus_query("/items/videos", params))
    return {"items": data.get("data", []), "total": data.get("meta", {}).get("filter_count", 0)}


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
    channel_matches = await directus._request("GET", directus_query("/items/channels", {
        "filter[name][_icontains]": q,
        "fields": "id",
        "limit": "-1",
    }))
    channel_ids = [c["id"] for c in channel_matches.get("data", [])]
    params = {
        "sort": "-uploaded_at",
        "limit": str(UI_PAGE_SIZE),
        "offset": str((page - 1) * UI_PAGE_SIZE),
        "meta": "filter_count",
        "fields": UI_VIDEO_FIELDS,
    }
    apply_ui_video_filters(
        params, q, status_filter, ai_filter, members_filter,
        search_transcript=True, search_channel_ids=channel_ids,
    )
    data = await directus._request("GET", directus_query("/items/videos", params))
    return {"items": data.get("data", []), "total": data.get("meta", {}).get("filter_count", 0)}


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
    params = {
        "filter[uploaded_at][_gte]": start.isoformat(),
        "filter[uploaded_at][_lt]": end.isoformat(),
        "sort": "-uploaded_at",
        "limit": "-1",
        "fields": UI_VIDEO_FIELDS,
        **NOT_MEMBERS_ONLY,
    }
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("data", [])


@router.get("/ui/videos/count")
async def ui_video_count():
    return {"count": await count_ui_videos(NOT_MEMBERS_ONLY)}


@router.get("/ui/admin-stats")
async def ui_admin_stats():
    local_tz = config.get_scheduler_timezone()
    local_start = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start.astimezone(timezone.utc)
    end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    total, today_count, errors, missing_transcripts, missing_ai = await asyncio.gather(
        count_ui_videos(NOT_MEMBERS_ONLY),
        count_ui_videos({
            "filter[uploaded_at][_gte]": start.isoformat(),
            "filter[uploaded_at][_lt]": end.isoformat(),
            **NOT_MEMBERS_ONLY,
        }),
        count_ui_videos({"filter[status][_eq]": "error", **NOT_MEMBERS_ONLY}),
        count_ui_videos({
            "filter[_and][0][_or][0][transcript][_null]": "true",
            "filter[_and][0][_or][1][status][_in]": "pending,no_transcript,error",
            "filter[_and][1][_or][0][is_members_only][_neq]": "true",
            "filter[_and][1][_or][1][is_members_only][_null]": "true",
        }),
        count_ui_videos({
            "filter[_and][0][transcript][_nnull]": "true",
            "filter[_and][1][_or][0][summary][_null]": "true",
            "filter[_and][1][_or][1][critique][_null]": "true",
            "filter[_and][2][_or][0][is_members_only][_neq]": "true",
            "filter[_and][2][_or][1][is_members_only][_null]": "true",
        }),
    )
    return {
        "totalVideos": total,
        "todayVideos": today_count,
        "errorVideos": errors,
        "missingTranscripts": missing_transcripts,
        "missingAiNotes": missing_ai,
    }


@router.get("/ui/channel-coverage")
async def ui_channel_coverage():
    base_params = {"aggregate[count]": "id", "groupBy[]": "channel_id", "limit": "-1"}
    total, transcript_done, ai_done = await asyncio.gather(
        directus._request("GET", directus_query("/items/videos", {**base_params, **NOT_MEMBERS_ONLY})),
        directus._request("GET", directus_query("/items/videos", {**base_params, "filter[status][_eq]": "done", **NOT_MEMBERS_ONLY})),
        directus._request("GET", directus_query("/items/videos", {**base_params, "filter[ai_notes_status][_eq]": "done", **NOT_MEMBERS_ONLY})),
    )
    return {
        "total": total.get("data", []),
        "transcriptDone": transcript_done.get("data", []),
        "aiDone": ai_done.get("data", []),
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
    params = {"filter[uploaded_at][_gte]": cutoff.isoformat(), "fields": "uploaded_at", "limit": "-1", **NOT_MEMBERS_ONLY}
    data = await directus._request("GET", directus_query("/items/videos", params))
    counts: dict[str, int] = {}
    for video in data.get("data", []):
        uploaded = video.get("uploaded_at")
        if uploaded:
            key = uploaded[:7]
            counts[key] = counts.get(key, 0) + 1
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
    params = {
        "filter[status][_eq]": "error",
        "fields": "id,video_id,title,url,channel_id.name,channel_id.channel_handle",
        "sort": "-processed_at",
        "limit": "50",
    }
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("data", [])


@router.patch("/ui/videos/{video_id}")
async def ui_update_video(video_id: str, data: dict):
    update = {key: value for key, value in data.items() if key in UI_VIDEO_UPDATE_FIELDS}
    if not update:
        raise HTTPException(status_code=400, detail="No supported video fields")
    return await directus.update_video(video_id, update)


@router.get("/ui/channels/{channel_id}/videos")
async def ui_channel_videos(channel_id: str, sort: str = "-uploaded_at"):
    params = {
        "filter[channel_id][_eq]": channel_id,
        "sort": sort,
        "limit": "-1",
        "fields": UI_VIDEO_FIELDS,
    }
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("data", [])
