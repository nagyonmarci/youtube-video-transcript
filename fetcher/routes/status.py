"""Health, status, resources, schedule, and settings endpoints."""

import asyncio
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import config
import worker_state
from api_models import ScheduleRequest, AppSettingsRequest
from constants import STREAM_UPDATE_INTERVAL, QUEUE_QUICK
from directus_client import now_iso
from job_ops import apply_ai_worker_queue_gate, current_job_snapshot
from job_utils import job_status_counts
from scheduler import start_refresh_scheduler
from worker_state import directus

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/health")
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


@router.get("/status")
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


@router.get("/resources")
async def resources():
    return await current_resource_status()


@router.get("/resources/stream")
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


@router.get("/schedule")
async def get_schedule():
    return {"cron": config.REFRESH_CRON, "timezone": config.SCHEDULER_TIMEZONE}


@router.patch("/schedule")
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


@router.get("/settings")
async def get_settings():
    return config.current_app_settings()


@router.patch("/settings")
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
