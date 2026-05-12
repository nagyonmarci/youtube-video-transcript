"""Job operations: enqueue helpers, cancel, clear AI notes, cleanup, backfill."""

import logging
import time
from typing import Optional

import config
import worker_state
from constants import QUEUE_QUICK, QUEUE_AI, JOB_QUICK_NOTE_VIDEO, JOB_AI_NOTE_VIDEO
from db import get_pg_pool
from directus_client import now_iso
from job_utils import job_dedupe_key, update_video_ai_status, job_duration_seconds
from worker_state import directus

logger = logging.getLogger(__name__)


async def apply_ai_worker_queue_gate(enabled: bool) -> int:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        if enabled:
            result = await conn.execute(
                """
                UPDATE jobs
                SET status = 'queued', error_message = NULL
                WHERE queue = 'ai'
                  AND status = 'paused'
                  AND error_message = 'Paused by AI worker control'
                """
            )
        else:
            result = await conn.execute(
                """
                UPDATE jobs
                SET status = 'paused', error_message = 'Paused by AI worker control'
                WHERE queue = 'ai'
                  AND status = 'queued'
                """
            )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def enqueue_quick_job(task: dict, label: Optional[str] = None):
    """Create a persistent quick-summary job."""
    return await directus.create_job(QUEUE_QUICK, task, label=label, dedupe_key=job_dedupe_key(QUEUE_QUICK, task))


async def enqueue_ai_note(video_id: str):
    """Mark a video as queued for AI notes and route it to the first pipeline step."""
    await update_video_ai_status(video_id, "pending")
    if config.AI_NOTES_QUICK_ENABLED:
        task = {"type": JOB_QUICK_NOTE_VIDEO, "video_id": video_id}
        return await directus.create_job(QUEUE_QUICK, task, dedupe_key=job_dedupe_key(QUEUE_QUICK, task))
    task = {"type": JOB_AI_NOTE_VIDEO, "video_id": video_id}
    return await directus.create_job(QUEUE_AI, task, dedupe_key=job_dedupe_key(QUEUE_AI, task))


async def enqueue_fetch_job(task: dict, label: Optional[str] = None):
    """Create a persistent fetch job."""
    return await directus.create_job("fetch", task, label=label, dedupe_key=job_dedupe_key("fetch", task))


async def enqueue_ai_job(task: dict, label: Optional[str] = None):
    """Create a persistent AI job."""
    return await directus.create_job("ai", task, label=label, dedupe_key=job_dedupe_key("ai", task))


async def maybe_enqueue_ai_year_backfill(source: str = "scheduler", force: bool = False) -> dict:
    """Keep the AI queue filled with missing notes for the configured upload year."""
    if not config.AI_NOTES_AUTO or not config.AI_NOTES_YEAR_BACKFILL_ENABLED or worker_state.stop_flag or worker_state.stop_ai_flag:
        return {"enabled": False, "queued": 0, "skipped": 0}

    now = time.monotonic()
    if not force and source != "scheduler" and now - worker_state.last_ai_year_backfill_attempt < config.AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS:
        return {"throttled": True, "queued": 0, "skipped": 0}
    worker_state.last_ai_year_backfill_attempt = now

    active_jobs = await directus.count_jobs("ai", "queued,running,paused")
    if not force and active_jobs >= config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE:
        return {
            "queued": 0,
            "skipped": 0,
            "active_jobs": active_jobs,
            "target_active": config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            "year": config.AI_NOTES_YEAR_BACKFILL_YEAR,
        }

    capacity = config.AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT if force else min(
        config.AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        max(0, config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE - active_jobs),
    )
    if capacity <= 0:
        return {"queued": 0, "skipped": 0, "active_jobs": active_jobs}

    missing_total = await directus.count_videos_missing_ai_notes(config.AI_NOTES_YEAR_BACKFILL_YEAR)
    if missing_total <= 0:
        logger.info(f"AI year backfill complete for {config.AI_NOTES_YEAR_BACKFILL_YEAR}")
        return {
            "queued": 0,
            "skipped": 0,
            "missing_total": 0,
            "year": config.AI_NOTES_YEAR_BACKFILL_YEAR,
        }

    active_video_ids = await directus.get_ai_note_job_video_ids()
    scan_limit = min(config.AI_NOTES_MAX_BATCH_LIMIT, max(capacity * 5, capacity + len(active_video_ids)))
    videos = await directus.get_videos_missing_ai_notes(scan_limit, year=config.AI_NOTES_YEAR_BACKFILL_YEAR)

    queued = 0
    skipped = 0
    for video in videos:
        if queued >= capacity or worker_state.stop_flag or worker_state.stop_ai_flag:
            break
        video_id = video["id"]
        if video_id in active_video_ids:
            skipped += 1
            continue
        await update_video_ai_status(video_id, "pending")
        job = await enqueue_ai_job({
            "type": "ai_note_video",
            "video_id": video_id,
            "backfill_year": config.AI_NOTES_YEAR_BACKFILL_YEAR,
        })
        active_video_ids.add(video_id)
        if job.get("existing"):
            skipped += 1
        else:
            queued += 1

    if queued or source == "scheduler":
        logger.info(
            "AI year backfill %s: queued=%s skipped=%s missing_total=%s active_jobs=%s year=%s",
            source,
            queued,
            skipped,
            missing_total,
            active_jobs,
            config.AI_NOTES_YEAR_BACKFILL_YEAR,
        )
    return {
        "queued": queued,
        "skipped": skipped,
        "missing_total": missing_total,
        "active_jobs": active_jobs,
        "target_active": config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
        "year": config.AI_NOTES_YEAR_BACKFILL_YEAR,
    }


async def clear_ai_notes(video_id: str) -> dict:
    """Remove generated AI notebook fields from a video without touching transcript data."""
    return await directus.update_video(video_id, {
        "summary": None,
        "topics": None,
        "takeaways": None,
        "questions": None,
        "obsidian_note": None,
        "study_guide": None,
        "critique": None,
        "ai_notes_status": None,
        "ai_notes_generated_at": None,
        "ai_notes_error": None,
    })


async def cancel_jobs(queue: Optional[str] = None, predicate=None, include_running: bool = False) -> int:
    """Mark queued/paused (and optionally running) jobs as cancelled. Return count."""
    cancellable = {"queued", "paused"}
    if include_running:
        cancellable.add("running")
    removed = 0
    for job in await directus.list_jobs():
        if queue and job.get("queue") != queue:
            continue
        if job.get("status") not in cancellable:
            continue
        task = job.get("payload") or {}
        if predicate and not predicate(task):
            continue
        await directus.update_job(job["id"], {
            "status": "cancelled",
            "finished_at": now_iso(),
            "error_message": "Cancelled by user",
        })
        removed += 1
    return removed


async def cleanup_orphan_ai_pending_videos() -> int:
    """Clear stale AI pending flags when no queued/running/paused AI job owns them."""
    active_video_ids = await directus.get_ai_note_job_video_ids()
    pending_videos = await directus.get_videos_with_ai_status("pending")
    cleaned = 0
    for video in pending_videos:
        if video["id"] in active_video_ids:
            continue
        await directus.update_video(video["id"], {
            "ai_notes_status": None,
            "ai_notes_error": "AI job was not found; status cleared automatically",
        })
        cleaned += 1
    if cleaned:
        logger.info(f"Cleared {cleaned} orphan AI pending video statuses")
    return cleaned


async def current_job_snapshot(queue: str, in_memory: dict, in_memory_job_id: Optional[str]) -> dict:
    """Return current in-memory job info, falling back to a persisted running job."""
    if in_memory_job_id:
        started = in_memory.get("started_at")
        duration = in_memory.get("duration_seconds")
        if started and duration is None:
            duration = job_duration_seconds({"started_at": started})
        return {**in_memory, "job_id": in_memory_job_id, "duration_seconds": duration}
    running = await directus.get_running_job(queue)
    if not running:
        return {}
    payload = running.get("payload") or {}
    progress_label = running.get("progress_label")
    return {
        "type": running.get("type") or payload.get("type"),
        "phase": progress_label or "running",
        "video": running.get("label"),
        "video_id": payload.get("video_id"),
        "job_id": running.get("id"),
        "progress_current": running.get("progress_current"),
        "progress_total": running.get("progress_total"),
        "progress_label": progress_label,
        "started_at": running.get("started_at"),
        "duration_seconds": running.get("duration_seconds") or job_duration_seconds(running),
        "metrics": running.get("metrics"),
    }


async def cleanup_old_jobs():
    """Delete done/cancelled jobs older than config.JOB_CLEANUP_DAYS days."""
    count = await directus.delete_old_jobs(older_than_days=config.JOB_CLEANUP_DAYS)
    if count > 0:
        logger.info(f"Cleaned up {count} old jobs (>{config.JOB_CLEANUP_DAYS}d)")
