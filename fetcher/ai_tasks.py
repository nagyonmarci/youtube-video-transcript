"""AI queue task handlers: generate notes, quick summary."""

import asyncio
import logging
from typing import Optional

import config
import worker_state
from ai_notes import generate_ai_notes, generate_quick_summary
from constants import STOPPED_BY_USER, QUEUE_QUICK, JOB_QUICK_NOTE_VIDEO, JOB_AI_NOTE_VIDEO
from directus_client import now_iso
from job_ops import enqueue_ai_job
from job_utils import (
    update_video_ai_status, update_job_progress, update_current_job_phase,
    summarize_ai_metrics, job_duration_seconds,
)
from worker_state import directus

logger = logging.getLogger(__name__)


async def generate_and_store_ai_notes(directus_video_id: str, video: dict, fields: Optional[list[str]] = None) -> bool:
    """Generate and persist AI notebook fields for a single Directus video."""
    requested_fields = [field for field in (fields or []) if field in config.AI_NOTE_GENERATED_FIELDS]
    worker_state.current_ai_task_info = {
        "type": "ai_note_video",
        "phase": "AI jegyzet generálása",
        "video_id": directus_video_id,
        "video": video.get("title") or video.get("video_id") or directus_video_id,
    }
    await update_video_ai_status(directus_video_id, "pending")
    try:
        async def ai_progress(progress: dict) -> None:
            phase = progress.get("phase") or "generating"
            label = progress.get("progress_label")
            extra = {key: value for key, value in progress.items() if key not in {"phase", "progress_label"}}
            try:
                await update_current_job_phase("ai", phase, label, extra)
            except Exception as progress_error:
                logger.warning(f"Could not update AI progress: {progress_error}")

        notes = await generate_ai_notes(video, progress_callback=ai_progress)
        if not notes:
            await update_video_ai_status(directus_video_id, "error", "No transcript available for AI notes")
            return False

        metrics = notes.pop("_metrics", None)
        if requested_fields:
            notes = {field: notes.get(field) for field in requested_fields if field in notes}
        if worker_state.current_ai_job_id and metrics:
            await directus.update_job(worker_state.current_ai_job_id, {
                "metrics": metrics,
                "progress_label": summarize_ai_metrics(metrics),
            })
            worker_state.current_ai_task_info["metrics"] = metrics
            worker_state.current_ai_task_info["progress_label"] = summarize_ai_metrics(metrics)
        await directus.update_video(directus_video_id, {
            **notes,
            "ai_notes_status": "done",
            "ai_notes_error": None,
            "ai_notes_generated_at": now_iso(),
        })
        logger.info(f"AI notes generated for {video.get('video_id') or directus_video_id}")
        return True
    except asyncio.CancelledError:
        logger.info(f"AI notes stopped for {video.get('video_id') or directus_video_id}")
        try:
            await asyncio.shield(update_video_ai_status(directus_video_id, "error", STOPPED_BY_USER))
        except Exception as update_error:
            logger.warning(f"Could not persist stopped AI note status: {update_error}")
        raise
    except Exception as e:
        error_message = str(e) or repr(e)
        logger.warning(f"AI notes failed for {video.get('video_id') or directus_video_id}: {error_message}")
        await update_video_ai_status(directus_video_id, "error", error_message[:1000])
        return False


async def process_ai_notes_task(task: dict):
    """Fan out a global AI notes batch into per-video jobs."""
    limit = max(1, min(int(task.get("limit") or config.AI_NOTES_BATCH_LIMIT), config.AI_NOTES_MAX_BATCH_LIMIT))
    videos = await directus.get_videos_missing_ai_notes(limit)
    active_video_ids = await directus.get_ai_note_job_video_ids()
    logger.info(f"Queueing AI note jobs for {len(videos)} candidate videos")

    queued = 0
    skipped = 0
    for i, video in enumerate(videos):
        if worker_state.stop_flag or worker_state.stop_ai_flag:
            break
        video_id = video["id"]
        worker_state.current_ai_task_info = {
            "type": "ai_notes",
            "phase": f"{i+1}/{len(videos)}",
            "video_id": video_id,
            "video": video.get("title") or video.get("video_id"),
        }
        await update_job_progress("ai", i + 1, len(videos), video.get("title") or video.get("video_id"))
        if video_id in active_video_ids:
            skipped += 1
            continue
        await update_video_ai_status(video_id, "pending")
        job = await enqueue_ai_job({"type": "ai_note_video", "video_id": video_id})
        active_video_ids.add(video_id)
        if job.get("existing"):
            skipped += 1
        else:
            queued += 1

    logger.info(f"AI notes fan-out complete: {queued} queued, {skipped} skipped")


async def process_single_ai_note_task(task: dict):
    """Generate AI notes for a selected video."""
    video_id = task["video_id"]
    video = await directus.get_video(video_id)
    if not video:
        logger.warning(f"AI notes video not found: {video_id}")
        return
    if not (video.get("transcript") or video.get("transcript_timed")):
        await update_video_ai_status(video_id, "error", "No transcript available for AI notes")
        return

    worker_state.current_ai_task_info = {
        "type": "ai_note_video",
        "phase": "generating",
        "video_id": video_id,
        "video": video.get("title") or video.get("video_id"),
        "started_at": now_iso(),
    }
    if worker_state.current_ai_job_id:
        await directus.update_job(worker_state.current_ai_job_id, {"progress_label": "AI generation started"})
    fields = task.get("fields")
    await generate_and_store_ai_notes(video_id, video, fields if isinstance(fields, list) else None)
    elapsed = job_duration_seconds({"started_at": worker_state.current_ai_task_info.get("started_at")})
    worker_state.current_ai_task_info["duration_seconds"] = elapsed
    if worker_state.current_ai_job_id and elapsed is not None:
        await directus.update_job(worker_state.current_ai_job_id, {
            "progress_label": f"AI generation finished in {elapsed}s",
        })


async def process_quick_note_task(task: dict):
    """Generate a quick summary for a video then enqueue it for full AI notes."""
    video_id = task["video_id"]
    video = await directus.get_video(video_id)
    if not video:
        logger.warning(f"Quick note video not found: {video_id}")
        return
    if not (video.get("transcript") or video.get("transcript_timed")):
        await update_video_ai_status(video_id, "error", "No transcript available for quick summary")
        return

    worker_state.current_quick_task_info = {
        "type": JOB_QUICK_NOTE_VIDEO,
        "phase": "quick_summary",
        "video_id": video_id,
        "video": video.get("title") or video.get("video_id"),
        "started_at": now_iso(),
    }

    async def quick_progress(progress: dict) -> None:
        label = progress.get("progress_label")
        try:
            await update_current_job_phase(QUEUE_QUICK, progress.get("phase", "quick_summary"), label, {})
        except Exception as e:
            logger.warning(f"Could not update quick progress: {e}")

    try:
        quick = await generate_quick_summary(video, progress_callback=quick_progress)
        if quick:
            await directus.update_video(video["id"], {
                "quick_summary": quick,
                "quick_summary_model": config.OLLAMA_QUICK_MODEL,
                "quick_summary_generated_at": now_iso(),
            })
            logger.info(f"Quick summary stored for {video.get('video_id') or video_id}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"Quick summary failed for {video_id} (continuing to full notes): {e}")

    # Always enqueue full notes, even if quick summary failed
    await enqueue_ai_job({"type": JOB_AI_NOTE_VIDEO, "video_id": video_id})
