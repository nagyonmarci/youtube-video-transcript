"""
YouTube Transcript Fetcher Service
FastAPI microservice that fetches YouTube channel/video transcripts
and stores them in Directus CMS.
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import scheduler as scheduler_module
from scheduler import start_refresh_scheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from api_models import (
    FetchChannelsRequest, FetchVideoRequest, ScheduleRequest, AppSettingsRequest,
    AiNotesRequest, ChannelAiNotesRequest, AiNoteRegenerateRequest, JobMoveRequest,
)

from db import close_pg_pool
from job_utils import (
    job_dedupe_key, update_job_progress, update_current_job_phase,
    job_status_counts, reset_stale_running_jobs_if_due, retry_or_fail_job,
    update_video_ai_status, heartbeat_job, normalize_claimed_job,
    parse_datetime, job_duration_seconds, summarize_ai_metrics,
    claim_next_job, reset_stale_running_jobs, reset_owned_running_jobs,
)
from job_ops import (
    apply_ai_worker_queue_gate, enqueue_quick_job, enqueue_ai_note,
    enqueue_fetch_job, enqueue_ai_job, maybe_enqueue_ai_year_backfill,
    clear_ai_notes, cancel_jobs, cleanup_orphan_ai_pending_videos,
    current_job_snapshot, cleanup_old_jobs,
)
import httpx

from ai_tasks import generate_and_store_ai_notes
from constants import (
    STREAM_UPDATE_INTERVAL,
    QUEUE_QUICK,
    JOB_QUICK_NOTE_VIDEO,
)
from directus_client import DirectusClient, now_iso
import config
import worker_state
from worker_state import directus
from workers import (
    bootstrap_runtime, create_worker_tasks, restart_ai_worker,
    worker_loop, ai_worker_loop, quick_worker_loop, run_worker_service,
)
from youtube_fetcher import (
    fetch_channel_name,
    parse_channel_input,
    extract_handle_from_url,
    rate_limited_sleep_channel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


















async def get_ollama_resource_status() -> dict:
    result = {
        "online": False,
        "base_url": config.OLLAMA_BASE_URL,
        "configured_model": config.OLLAMA_CHAT_MODEL,
        "models": [],
        "sampled_at": now_iso(),
        "error": None,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0)) as client:
            response = await client.get(f"{config.OLLAMA_BASE_URL}/api/ps")
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        result["error"] = str(e)[:300]
        return result

    models = []
    for item in data.get("models", []):
        size = int(item.get("size") or 0)
        size_vram = int(item.get("size_vram") or 0)
        processor_percent = round((size_vram / size) * 100) if size > 0 and size_vram > 0 else None
        details = item.get("details") or {}
        models.append({
            "name": item.get("name") or item.get("model"),
            "model": item.get("model") or item.get("name"),
            "size": size,
            "size_vram": size_vram,
            "processor_percent": processor_percent,
            "context_length": item.get("context_length"),
            "expires_at": item.get("expires_at"),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
        })

    result["online"] = True
    result["models"] = models
    return result


async def current_resource_status() -> dict:
    ai_counts = await job_status_counts("ai")
    return {
        "ai_worker_enabled": config.AI_NOTES_WORKER_ENABLED,
        "ai_job_cooldown_seconds": config.AI_NOTES_JOB_COOLDOWN_SECONDS,
        "ai_worker_concurrency": config.AI_WORKER_CONCURRENCY,
        "ai_queue": ai_counts,
        "ollama": await get_ollama_resource_status(),
    }











# ---- App lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bootstrap_runtime(cleanup_pending=config.FETCHER_ROLE in {"api", "all"})

    worker_tasks = []
    if config.FETCHER_ROLE in {"all", "worker"}:
        worker_tasks = create_worker_tasks()
        worker_state.worker_task = next((task for task in worker_tasks if "fetch" in task.get_name()), None)
        worker_state.ai_worker_task = next((task for task in worker_tasks if "ai" in task.get_name()), None)

    if config.FETCHER_ROLE in {"api", "all"}:
        start_refresh_scheduler()
    else:
        logger.info(f"Fetcher API started in role={config.FETCHER_ROLE}; scheduler disabled")

    yield

    # Cleanup
    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    if scheduler_module.scheduler:
        scheduler_module.scheduler.shutdown(wait=False)
    await close_pg_pool()
    await directus.close()


app = FastAPI(title="YouTube Transcript Fetcher", lifespan=lifespan)


@app.middleware("http")
async def require_app_token(request: Request, call_next):
    if config.APP_API_TOKEN and request.url.path not in {"/health"}:
        if request.headers.get("x-app-token") != config.APP_API_TOKEN:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=config.APP_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)





UI_PAGE_SIZE = 100
UI_VIDEO_FIELDS = ",".join([
    "id,video_id,title,url,thumbnail_url,uploaded_at,duration_seconds,status,is_members_only,transcript,transcript_timed,whisper_status",
    "quick_summary,quick_summary_model,quick_summary_generated_at",
    "summary,topics,takeaways,questions,obsidian_note,study_guide,critique,ai_notes_status,ai_notes_generated_at,ai_notes_error",
    "channel_id.id,channel_id.name,channel_id.channel_handle",
])
UI_CHANNEL_UPDATE_FIELDS = {"name", "channel_url", "channel_handle", "status", "video_count", "error_message", "last_refreshed"}
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


def directus_query(path: str, params: dict) -> str:
    return f"{path}?{urlencode(params)}"


def apply_ui_video_filters(params: dict, search: str, status_filter: str, ai_filter: str, members_filter: str) -> None:
    if search:
        params["filter[title][_icontains]"] = search
    if status_filter and status_filter != "all":
        params["filter[status][_eq]"] = status_filter
    if ai_filter == "done":
        params["filter[ai_notes_status][_eq]"] = "done"
    elif ai_filter == "missing":
        params["filter[_and][0][transcript][_nnull]"] = "true"
        params["filter[_and][1][summary][_null]"] = "true"
    elif ai_filter == "error":
        params["filter[ai_notes_status][_eq]"] = "error"
    if members_filter == "hide":
        params["filter[_or][0][is_members_only][_neq]"] = "true"
        params["filter[_or][1][is_members_only][_null]"] = "true"
    elif members_filter == "only":
        params["filter[is_members_only][_eq]"] = "true"


async def count_ui_videos(extra_params: Optional[dict] = None) -> int:
    params = {"limit": "1", "meta": "filter_count", "fields": "id"}
    if extra_params:
        params.update(extra_params)
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("meta", {}).get("filter_count", 0)


# ---- API Endpoints ----


@app.get("/ui/channels")
async def ui_channels():
    data = await directus._request("GET", "/items/channels?sort[]=-added_at&limit=-1")
    count_data = await directus._request("GET", "/items/videos?aggregate[count]=id&groupBy[]=channel_id&limit=-1")
    counts = {
        row.get("channel_id"): int((row.get("count") or {}).get("id") or 0)
        for row in count_data.get("data", [])
        if row.get("channel_id")
    }
    return [
        {**channel, "video_count": counts.get(channel.get("id"), 0)}
        for channel in data.get("data", [])
    ]


@app.patch("/ui/channels/{channel_id}")
async def ui_update_channel(channel_id: str, data: dict):
    update = {key: value for key, value in data.items() if key in UI_CHANNEL_UPDATE_FIELDS}
    if not update:
        raise HTTPException(status_code=400, detail="No supported channel fields")
    return await directus.update_channel(channel_id, update)


@app.delete("/ui/channels/{channel_id}")
async def ui_delete_channel(channel_id: str):
    await directus._request("DELETE", f"/items/channels/{channel_id}")
    return {"deleted": True, "id": channel_id}


@app.get("/ui/videos")
async def ui_videos(
    channel_id: Optional[str] = None,
    sort: str = "-uploaded_at",
    page: int = 1,
    search: str = "",
    status_filter: str = "all",
    ai_filter: str = "all",
    members_filter: str = "all",
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


@app.get("/ui/videos/daily")
async def ui_daily_videos(date: str, tz: str = "Europe/Budapest"):
    try:
        local_tz = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, KeyError):
        local_tz = timezone.utc
    year, month, day = (int(x) for x in date.split("-"))
    local_start = datetime(year, month, day, tzinfo=local_tz)
    start = local_start.astimezone(timezone.utc)
    end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    params = {
        "filter[uploaded_at][_gte]": start.isoformat(),
        "filter[uploaded_at][_lt]": end.isoformat(),
        "sort": "-uploaded_at",
        "limit": "-1",
        "fields": UI_VIDEO_FIELDS,
    }
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("data", [])


@app.get("/ui/videos/count")
async def ui_video_count():
    return {"count": await count_ui_videos()}


@app.get("/ui/admin-stats")
async def ui_admin_stats():
    local_tz = config.get_scheduler_timezone()
    local_start = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start.astimezone(timezone.utc)
    end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    total, today_count, errors, missing_transcripts, missing_ai = await asyncio.gather(
        count_ui_videos(),
        count_ui_videos({
            "filter[uploaded_at][_gte]": start.isoformat(),
            "filter[uploaded_at][_lt]": end.isoformat(),
        }),
        count_ui_videos({"filter[status][_eq]": "error"}),
        count_ui_videos({
            "filter[_or][0][transcript][_null]": "true",
            "filter[_or][1][status][_in]": "pending,no_transcript,error",
        }),
        count_ui_videos({
            "filter[_and][0][transcript][_nnull]": "true",
            "filter[_and][1][_or][0][summary][_null]": "true",
            "filter[_and][1][_or][1][critique][_null]": "true",
        }),
    )
    return {
        "totalVideos": total,
        "todayVideos": today_count,
        "errorVideos": errors,
        "missingTranscripts": missing_transcripts,
        "missingAiNotes": missing_ai,
    }


@app.get("/ui/channel-coverage")
async def ui_channel_coverage():
    total, transcript_done, ai_done = await asyncio.gather(
        directus._request("GET", "/items/videos?aggregate[count]=id&groupBy[]=channel_id&limit=-1"),
        directus._request("GET", "/items/videos?filter[status][_eq]=done&aggregate[count]=id&groupBy[]=channel_id&limit=-1"),
        directus._request("GET", "/items/videos?filter[ai_notes_status][_eq]=done&aggregate[count]=id&groupBy[]=channel_id&limit=-1"),
    )
    return {
        "total": total.get("data", []),
        "transcriptDone": transcript_done.get("data", []),
        "aiDone": ai_done.get("data", []),
    }


@app.get("/ui/monthly-video-counts")
async def ui_monthly_video_counts():
    cutoff = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = cutoff.month - 11
    year = cutoff.year
    while month <= 0:
        month += 12
        year -= 1
    cutoff = cutoff.replace(year=year, month=month)
    params = {"filter[uploaded_at][_gte]": cutoff.isoformat(), "fields": "uploaded_at", "limit": "-1"}
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


@app.get("/ui/error-videos")
async def ui_error_videos():
    params = {
        "filter[status][_eq]": "error",
        "fields": "id,video_id,title,url,channel_id.name,channel_id.channel_handle",
        "sort": "-processed_at",
        "limit": "50",
    }
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("data", [])


@app.patch("/ui/videos/{video_id}")
async def ui_update_video(video_id: str, data: dict):
    update = {key: value for key, value in data.items() if key in UI_VIDEO_UPDATE_FIELDS}
    if not update:
        raise HTTPException(status_code=400, detail="No supported video fields")
    return await directus.update_video(video_id, update)


@app.get("/ui/channels/{channel_id}/videos")
async def ui_channel_videos(channel_id: str, sort: str = "-uploaded_at"):
    params = {
        "filter[channel_id][_eq]": channel_id,
        "sort": sort,
        "limit": "-1",
        "fields": UI_VIDEO_FIELDS,
    }
    data = await directus._request("GET", directus_query("/items/videos", params))
    return data.get("data", [])

@app.get("/health")
async def health():
    fetch_counts = await job_status_counts("fetch")
    ai_counts = await job_status_counts("ai")
    return {
        "status": "ok",
        "queue_size": fetch_counts["queued"],
        "ai_queue_size": ai_counts["queued"],
        "fetch_active_size": fetch_counts["active"],
        "ai_active_size": ai_counts["active"],
        "queues": {
            "fetch": fetch_counts,
            "ai": ai_counts,
        },
        "workers": {
            "fetch_concurrency": config.FETCH_WORKER_CONCURRENCY,
            "ai_concurrency": config.AI_WORKER_CONCURRENCY,
        },
    }


@app.get("/status")
async def status():
    fetch_current = await current_job_snapshot("fetch", worker_state.current_task_info, worker_state.current_job_id)
    quick_current = await current_job_snapshot(QUEUE_QUICK, worker_state.current_quick_task_info, worker_state.current_quick_job_id)
    ai_current = await current_job_snapshot("ai", worker_state.current_ai_task_info, worker_state.current_ai_job_id)
    ollama_resources = await get_ollama_resource_status()
    fetch_counts = await job_status_counts("fetch")
    quick_counts = await job_status_counts(QUEUE_QUICK)
    ai_counts = await job_status_counts("ai")
    ai_year_missing = None
    if config.AI_NOTES_AUTO and config.AI_NOTES_YEAR_BACKFILL_ENABLED:
        ai_year_missing = await directus.count_videos_missing_ai_notes(config.AI_NOTES_YEAR_BACKFILL_YEAR)
    return {
        "queue_size": fetch_counts["queued"],
        "quick_queue_size": quick_counts["queued"],
        "ai_queue_size": ai_counts["queued"],
        "fetch_active_size": fetch_counts["active"],
        "quick_active_size": quick_counts["active"],
        "ai_active_size": ai_counts["active"],
        "queues": {
            "fetch": fetch_counts,
            QUEUE_QUICK: quick_counts,
            "ai": ai_counts,
        },
        "workers": {
            "fetch_concurrency": config.FETCH_WORKER_CONCURRENCY,
            "quick_concurrency": config.QUICK_WORKER_CONCURRENCY,
            "ai_concurrency": config.AI_WORKER_CONCURRENCY,
        },
        "worker_state.stop_flag": worker_state.stop_flag,
        "stopped_queues": {
            "fetch": worker_state.stop_flag or worker_state.stop_fetch_flag,
            QUEUE_QUICK: worker_state.stop_flag or worker_state.stop_quick_flag,
            "ai": worker_state.stop_flag or worker_state.stop_ai_flag,
        },
        "current_task": fetch_current,
        "current_quick_task": quick_current,
        "current_ai_task": ai_current,
        "resources": {
            "ai_worker_enabled": config.AI_NOTES_WORKER_ENABLED,
            "ai_job_cooldown_seconds": config.AI_NOTES_JOB_COOLDOWN_SECONDS,
            "ai_worker_concurrency": config.AI_WORKER_CONCURRENCY,
            "ai_queue": ai_counts,
            "ollama": ollama_resources,
        },
        "schedule": {
            "cron": config.REFRESH_CRON,
            "timezone": config.SCHEDULER_TIMEZONE,
        },
        "ai_year_backfill": {
            "enabled": config.AI_NOTES_AUTO and config.AI_NOTES_YEAR_BACKFILL_ENABLED,
            "year": config.AI_NOTES_YEAR_BACKFILL_YEAR,
            "missing": ai_year_missing,
            "target_active": config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            "batch_limit": config.AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
            "interval_seconds": config.AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
        },
    }


@app.get("/jobs")
async def list_jobs():
    active_statuses = ["queued", "running", "paused", "error"]
    done_statuses = ["done", "cancelled"]
    active = await directus.list_jobs(statuses=active_statuses, limit=500)
    completed = await directus.list_jobs(statuses=done_statuses, limit=100)
    return {
        "jobs": active + completed,
        "counts": {
            "fetch": await job_status_counts("fetch"),
            "ai": await job_status_counts("ai"),
        },
        "current": {
            "fetch": worker_state.current_job_id,
            "ai": worker_state.current_ai_job_id,
        },
    }


@app.get("/resources")
async def resources():
    return await current_resource_status()


@app.get("/resources/stream")
async def resource_stream():
    async def events():
        while True:
            try:
                payload = await current_resource_status()
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as e:
                payload = {
                    "ai_worker_enabled": config.AI_NOTES_WORKER_ENABLED,
                    "ai_job_cooldown_seconds": config.AI_NOTES_JOB_COOLDOWN_SECONDS,
                    "ollama": {
                        "online": False,
                        "base_url": config.OLLAMA_BASE_URL,
                        "configured_model": config.OLLAMA_CHAT_MODEL,
                        "models": [],
                        "sampled_at": now_iso(),
                        "error": str(e)[:300],
                    },
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(STREAM_UPDATE_INTERVAL)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/ai-notes/cleanup-stale")
async def cleanup_stale_ai_notes():
    cleaned = await cleanup_orphan_ai_pending_videos()
    return {"cleaned": cleaned}


@app.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "running":
        raise HTTPException(status_code=400, detail="Running jobs cannot be paused; use stop")
    if job.get("status") in {"done", "cancelled"}:
        raise HTTPException(status_code=400, detail="Completed jobs cannot be paused")
    return await directus.update_job(job_id, {"status": "paused"})


@app.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in {"paused", "error", "cancelled"}:
        raise HTTPException(status_code=400, detail="Only paused, error, or cancelled jobs can be resumed")
    return await directus.update_job(job_id, {
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "error_message": None,
        "progress_current": None,
        "progress_total": None,
        "progress_label": None,
    })


@app.post("/jobs/{job_id}/start")
async def start_job_now(job_id: str):
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "running":
        return job
    return await directus.update_job(job_id, {
        "status": "queued",
        "sort_order": 0,
        "started_at": None,
        "finished_at": None,
        "error_message": None,
        "progress_current": None,
        "progress_total": None,
        "progress_label": None,
    })


@app.post("/jobs/{job_id}/move")
async def move_job(job_id: str, request: JobMoveRequest):
    direction = request.direction.lower().strip()
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="direction must be up or down")
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "running":
        raise HTTPException(status_code=400, detail="Running jobs cannot be reordered")

    jobs = [
        item for item in await directus.list_jobs()
        if item.get("queue") == job.get("queue") and item.get("status") in {"queued", "paused"}
    ]
    index = next((i for i, item in enumerate(jobs) if item["id"] == job_id), -1)
    if index < 0:
        raise HTTPException(status_code=400, detail="Job is not reorderable")
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(jobs):
        return job

    current = jobs[index]
    target = jobs[target_index]
    await directus.update_job(current["id"], {"sort_order": target.get("sort_order") or 0})
    await directus.update_job(target["id"], {"sort_order": current.get("sort_order") or 0})
    return {"moved": True, "job_id": job_id, "direction": direction}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cancelled_current = False
    if job.get("status") == "running":
        await directus.update_job(job_id, {
            "status": "cancelled",
            "finished_at": now_iso(),
            "error_message": "Cancelled by user",
            "locked_at": None,
            "locked_by": None,
        })
        return {"deleted": False, "cancelled": True, "job_id": job_id, "cancelled_current": False}

    if job_id == worker_state.current_job_id and worker_state.worker_task and not worker_state.worker_task.done():
        worker_state.worker_task.cancel()
        try:
            await worker_state.worker_task
        except asyncio.CancelledError:
            pass
        worker_state.worker_task = asyncio.create_task(worker_loop())
        cancelled_current = True
    if job_id == worker_state.current_ai_job_id and worker_state.ai_worker_task and not worker_state.ai_worker_task.done():
        await restart_ai_worker()
        cancelled_current = True

    await directus.delete_job(job_id)
    return {"deleted": True, "job_id": job_id, "cancelled_current": cancelled_current}


@app.get("/schedule")
async def get_schedule():
    return {"cron": config.REFRESH_CRON, "timezone": config.SCHEDULER_TIMEZONE}


@app.patch("/schedule")
async def update_schedule(request: ScheduleRequest):
    cron = request.cron.strip()
    timezone_name = request.timezone.strip()
    try:
        config.validate_schedule(cron, timezone_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    config.REFRESH_CRON = cron
    config.SCHEDULER_TIMEZONE = timezone_name
    start_refresh_scheduler()
    await worker_state.save_schedule_settings(cron, timezone_name)
    return {"cron": config.REFRESH_CRON, "timezone": config.SCHEDULER_TIMEZONE}


@app.get("/settings")
async def get_settings():
    return config.current_app_settings()


@app.patch("/settings")
async def update_settings(request: AppSettingsRequest):
    updates = request.model_dump(exclude_unset=True)
    next_settings = {**config.current_app_settings(), **updates}
    config.apply_app_settings(next_settings)
    gated_jobs = None
    if "ai_notes_worker_enabled" in updates:
        gated_jobs = await apply_ai_worker_queue_gate(config.AI_NOTES_WORKER_ENABLED)
    for key, value in config.current_app_settings().items():
        await directus.set_setting(key, str(value).lower() if isinstance(value, bool) else str(value))
    if config.FETCHER_ROLE in {"api", "all"}:
        start_refresh_scheduler()
    return {**config.current_app_settings(), "ai_worker_gated_jobs": gated_jobs}


@app.post("/fetch-channels")
async def fetch_channels(request: FetchChannelsRequest):
    """Queue multiple channel URLs for processing."""
    queued = []
    for raw_url in request.urls:
        raw_url = raw_url.strip()
        if not raw_url or raw_url.startswith("#"):
            continue

        channel_url = parse_channel_input(raw_url)
        if not channel_url:
            continue

        handle = extract_handle_from_url(channel_url)

        # Check if channel already exists
        existing = await directus.find_channel_by_handle(handle)
        if existing:
            channel_id = existing["id"]
            # Queue a refresh instead
            await enqueue_fetch_job({"type": "refresh", "channel_id": channel_id})
            queued.append({"url": channel_url, "action": "refresh", "id": channel_id})
        else:
            # Create channel record
            channel_record = await directus.create_channel({
                "name": handle,
                "channel_url": channel_url,
                "channel_handle": handle,
                "status": "pending",
                "video_count": 0,
            })
            channel_id = channel_record.get("id")

            # Try to get real name asynchronously (don't block)
            await enqueue_fetch_job({
                "type": "channel",
                "channel_url": channel_url,
                "channel_id": channel_id,
            })
            queued.append({"url": channel_url, "action": "fetch", "id": channel_id})

    return {"queued": queued, "count": len(queued)}


@app.post("/fetch-video")
async def fetch_video(request: FetchVideoRequest):
    """Queue a single video URL for processing."""
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    await enqueue_fetch_job({
        "type": "video",
        "video_url": url,
        "channel_id": request.channel_id,
    })
    return {"queued": True, "url": url}


@app.post("/refresh-channel/{channel_id}")
async def refresh_channel(channel_id: str):
    """Manually refresh a channel: fetch new videos and retry incomplete transcripts."""
    channel = await directus.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    await enqueue_fetch_job({"type": "refresh", "channel_id": channel_id})
    return {"queued": True, "channel_id": channel_id}


@app.post("/refresh-dates")
async def refresh_dates():
    """Queue a task to fetch missing upload dates for all videos."""
    existing = await directus.get_active_job_by_type("fetch", "refresh_dates")
    if existing:
        return {"queued": False, "existing": True, "job_id": existing["id"]}
    job = await enqueue_fetch_job({"type": "refresh_dates"})
    return {"queued": True, "job_id": job.get("id")}


@app.post("/refresh-thumbnails")
async def refresh_thumbnails():
    """Queue a task to fetch missing thumbnail URLs for all videos."""
    existing = await directus.get_active_job_by_type("fetch", "refresh_thumbnails")
    if existing:
        return {"queued": False, "existing": True, "job_id": existing["id"]}
    job = await enqueue_fetch_job({"type": "refresh_thumbnails"})
    return {"queued": True, "job_id": job.get("id")}


@app.post("/ai-notes")
async def ai_notes(request: AiNotesRequest):
    """Queue AI note generation for videos that have transcripts but no summary."""
    existing = await directus.get_active_job_by_type("ai", "ai_notes")
    if existing:
        return {"queued": False, "existing": True, "job_id": existing["id"]}
    limit = max(1, min(request.limit, config.AI_NOTES_MAX_BATCH_LIMIT))
    job = await enqueue_ai_job({"type": "ai_notes", "limit": limit})
    return {"queued": True, "limit": limit, "job_id": job.get("id")}


@app.post("/quick-notes/{video_id}")
async def quick_note_video(video_id: str):
    """Queue a priority quick summary job for one video (sort_order=0 → front of queue)."""
    video = await directus.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not (video.get("transcript") or video.get("transcript_timed")):
        raise HTTPException(status_code=400, detail="Video has no transcript")

    await update_video_ai_status(video_id, "pending")
    task = {"type": JOB_QUICK_NOTE_VIDEO, "video_id": video_id}
    job = await directus.create_job(
        QUEUE_QUICK, task,
        dedupe_key=job_dedupe_key(QUEUE_QUICK, task),
        sort_order=0,
    )
    return {"queued": not job.get("existing"), "existing": bool(job.get("existing")), "video_id": video_id, "job_id": job.get("id")}


@app.post("/ai-notes/{video_id}")
async def ai_note_video(video_id: str):
    """Queue AI note generation for one selected Directus video."""
    video = await directus.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not (video.get("transcript") or video.get("transcript_timed")):
        raise HTTPException(status_code=400, detail="Video has no transcript")

    await enqueue_ai_note(video_id)
    return {"queued": True, "video_id": video_id}


@app.post("/ai-notes/{video_id}/regenerate")
async def regenerate_ai_note_fields(video_id: str, request: AiNoteRegenerateRequest):
    """Queue regeneration for selected AI note fields on one video."""
    video = await directus.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not (video.get("transcript") or video.get("transcript_timed")):
        raise HTTPException(status_code=400, detail="Video has no transcript")

    fields = [field for field in request.fields if field in config.AI_NOTE_GENERATED_FIELDS]
    if not fields:
        raise HTTPException(status_code=400, detail="No supported AI note fields requested")

    await directus.update_video(video_id, {
        **{field: None for field in fields},
        "ai_notes_status": "pending",
        "ai_notes_error": None,
    })
    task = {"type": "ai_note_video", "video_id": video_id, "fields": fields}
    job = await enqueue_ai_job(task)
    return {"queued": not job.get("existing"), "existing": bool(job.get("existing")), "video_id": video_id, "fields": fields, "job_id": job.get("id")}


@app.post("/channels/{channel_id}/ai-notes")
async def ai_notes_for_channel(channel_id: str, request: ChannelAiNotesRequest):
    """Queue AI note generation for all missing AI notes in one channel."""
    channel = await directus.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    limit = max(1, min(request.limit, 1000))
    videos = await directus.get_channel_videos_missing_ai_notes(channel_id, limit)
    active_video_ids = await directus.get_ai_note_job_video_ids()
    queued = []
    skipped_active = 0

    for video in videos:
        video_id = video["id"]
        if video_id in active_video_ids:
            skipped_active += 1
            continue
        await directus.update_video(video_id, {
            "ai_notes_status": "pending",
            "ai_notes_error": None,
        })
        job = await enqueue_ai_job({"type": "ai_note_video", "video_id": video_id})
        active_video_ids.add(video_id)
        queued.append({"video_id": video_id, "title": video.get("title"), "job_id": job.get("id")})

    return {
        "queued": True,
        "channel_id": channel_id,
        "count": len(queued),
        "skipped_active": skipped_active,
        "limit": limit,
        "items": queued,
    }


@app.delete("/ai-notes/{video_id}")
async def delete_ai_note_video(video_id: str):
    """Delete generated AI note fields for one Directus video."""
    video = await directus.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    removed = await cancel_jobs(
        "ai",
        lambda task: task.get("type") == "ai_note_video" and task.get("video_id") == video_id,
    )
    cancelled_current = False
    if worker_state.current_ai_task_info.get("video_id") == video_id and worker_state.ai_worker_task and not worker_state.ai_worker_task.done():
        await restart_ai_worker()
        cancelled_current = True
    await clear_ai_notes(video_id)
    return {"deleted": True, "video_id": video_id, "removed": removed, "cancelled_current": cancelled_current}


@app.post("/stop")
async def stop_processing(queue: Optional[str] = None):
    """Pause a specific queue (fetch|quick|ai) or all if queue is omitted."""
    stop_fetch = queue in (None, "fetch")
    stop_quick = queue in (None, QUEUE_QUICK)
    stop_ai = queue in (None, "ai")

    if stop_fetch:
        worker_state.stop_fetch_flag = True
    if stop_quick:
        worker_state.stop_quick_flag = True
    if stop_ai:
        worker_state.stop_ai_flag = True
    if queue is None:
        worker_state.stop_flag = True

    drained = await cancel_jobs("fetch", include_running=True) if stop_fetch else 0
    quick_drained = await cancel_jobs(QUEUE_QUICK, include_running=True) if stop_quick else 0
    ai_drained = await cancel_jobs("ai", include_running=True) if stop_ai else 0

    return {
        "stopped": True,
        "queue": queue or "all",
        "drained": drained,
        "quick_drained": quick_drained,
        "ai_drained": ai_drained,
    }


@app.post("/resume")
async def resume_processing(queue: Optional[str] = None):
    """Resume processing after stop (fetch|quick|ai or all if omitted)."""
    if queue in (None, "fetch"):
        worker_state.stop_fetch_flag = False
    if queue in (None, QUEUE_QUICK):
        worker_state.stop_quick_flag = False
    if queue in (None, "ai"):
        worker_state.stop_ai_flag = False
    if queue is None:
        worker_state.stop_flag = False
    if queue in (None, "fetch") and (not worker_state.worker_task or worker_state.worker_task.done()):
        worker_state.worker_task = asyncio.create_task(worker_loop())
    if queue in (None, QUEUE_QUICK) and (not worker_state.quick_worker_task or worker_state.quick_worker_task.done()):
        worker_state.quick_worker_task = asyncio.create_task(quick_worker_loop())
    if queue in (None, "ai") and (not worker_state.ai_worker_task or worker_state.ai_worker_task.done()):
        worker_state.ai_worker_task = asyncio.create_task(ai_worker_loop())
    return {"resumed": True, "queue": queue or "all"}
