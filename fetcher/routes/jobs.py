"""Job CRUD endpoints — list, pause, resume, start, move, delete."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

import worker_state
from api_models import JobMoveRequest
from directus_client import now_iso
from job_ops import cleanup_orphan_ai_pending_videos
from job_utils import job_status_counts
from worker_state import directus
from workers import restart_ai_worker, worker_loop

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ai-notes/cleanup-stale")
async def cleanup_stale_ai_notes():
    cleaned = await cleanup_orphan_ai_pending_videos()
    return {"cleaned": cleaned}


@router.get("/jobs")
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


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "running":
        raise HTTPException(status_code=400, detail="Running jobs cannot be paused; use stop")
    if job.get("status") in {"done", "cancelled"}:
        raise HTTPException(status_code=400, detail="Completed jobs cannot be paused")
    return await directus.update_job(job_id, {"status": "paused"})


@router.post("/jobs/{job_id}/resume")
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


@router.post("/jobs/{job_id}/start")
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


@router.post("/jobs/{job_id}/move")
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


@router.delete("/jobs/{job_id}")
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
