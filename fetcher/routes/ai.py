"""AI notes endpoints and worker stop/resume controls."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

import config
import worker_state
from api_models import AiNotesRequest, ChannelAiNotesRequest, AiNoteRegenerateRequest
from constants import QUEUE_QUICK, JOB_QUICK_NOTE_VIDEO
from job_ops import (
    enqueue_ai_job, enqueue_ai_note, cancel_jobs, clear_ai_notes,
)
from job_utils import job_dedupe_key, update_video_ai_status
from worker_state import directus
from workers import restart_ai_worker, worker_loop, quick_worker_loop, ai_worker_loop

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ai-notes")
async def ai_notes(request: AiNotesRequest):
    """Queue AI note generation for videos that have transcripts but no summary."""
    existing = await directus.get_active_job_by_type("ai", "ai_notes")
    if existing:
        return {"queued": False, "existing": True, "job_id": existing["id"]}
    limit = max(1, min(request.limit or config.AI_NOTES_BATCH_LIMIT, config.AI_NOTES_MAX_BATCH_LIMIT))
    job = await enqueue_ai_job({"type": "ai_notes", "limit": limit})
    return {"queued": True, "limit": limit, "job_id": job.get("id")}


@router.post("/quick-notes/{video_id}")
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


@router.post("/ai-notes/{video_id}")
async def ai_note_video(video_id: str):
    """Queue AI note generation for one selected Directus video."""
    video = await directus.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not (video.get("transcript") or video.get("transcript_timed")):
        raise HTTPException(status_code=400, detail="Video has no transcript")

    await enqueue_ai_note(video_id)
    return {"queued": True, "video_id": video_id}


@router.post("/ai-notes/{video_id}/regenerate")
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


@router.post("/channels/{channel_id}/ai-notes")
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


@router.delete("/ai-notes/{video_id}")
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


@router.post("/stop")
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


@router.post("/resume")
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
