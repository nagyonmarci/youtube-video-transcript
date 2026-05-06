"""
YouTube Transcript Fetcher Service
FastAPI microservice that fetches YouTube channel/video transcripts
and stores them in Directus CMS.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_notes import generate_ai_notes
from directus_client import DirectusClient
from youtube_fetcher import (
    fetch_channel_videos,
    fetch_channel_name,
    fetch_video_info,
    fetch_video_date_info,
    fetch_transcript_variants,
    parse_uploaded_at,
    parse_channel_input,
    extract_handle_from_url,
    rate_limited_sleep_transcript,
    rate_limited_sleep_channel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055")
DIRECTUS_TOKEN = os.environ.get("DIRECTUS_TOKEN", "admin-token-change-me")
REFRESH_CRON = os.environ.get("REFRESH_CRON", "0 7 * * *")
SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Europe/Budapest")
AI_NOTES_AUTO = os.environ.get("AI_NOTES_AUTO", "true").lower() in {"1", "true", "yes", "on"}
AI_NOTES_BATCH_LIMIT = int(os.environ.get("AI_NOTES_BATCH_LIMIT", "10"))

directus = DirectusClient(DIRECTUS_URL, DIRECTUS_TOKEN)

# Worker state
task_queue: asyncio.Queue = asyncio.Queue()
ai_task_queue: asyncio.Queue = asyncio.Queue()
worker_task: Optional[asyncio.Task] = None
ai_worker_task: Optional[asyncio.Task] = None
stop_flag = False
current_task_info: dict = {}
current_ai_task_info: dict = {}
current_job_id: Optional[str] = None
current_ai_job_id: Optional[str] = None
scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler_timezone():
    try:
        return ZoneInfo(SCHEDULER_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning(f"Unknown scheduler timezone '{SCHEDULER_TIMEZONE}', falling back to UTC")
        return timezone.utc


def validate_schedule(cron: str, timezone_name: str):
    cron_parts = cron.split()
    if len(cron_parts) != 5:
        raise ValueError("A cron kifejezésnek pontosan 5 mezőből kell állnia")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Ismeretlen időzóna: {timezone_name}") from exc
    return cron_parts


async def load_schedule_settings():
    global REFRESH_CRON, SCHEDULER_TIMEZONE
    try:
        stored_cron = await directus.get_setting("refresh_cron")
        stored_timezone = await directus.get_setting("scheduler_timezone")
        if stored_cron:
            REFRESH_CRON = stored_cron
        if stored_timezone:
            SCHEDULER_TIMEZONE = stored_timezone
        validate_schedule(REFRESH_CRON, SCHEDULER_TIMEZONE)
    except Exception as e:
        logger.warning(f"Could not load stored schedule settings, using current values: {e}")


async def save_schedule_settings(cron: str, timezone_name: str):
    await directus.set_setting("refresh_cron", cron)
    await directus.set_setting("scheduler_timezone", timezone_name)


def start_refresh_scheduler():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)

    cron_parts = validate_schedule(REFRESH_CRON, SCHEDULER_TIMEZONE)
    minute, hour, day, month, day_of_week = cron_parts
    scheduler = AsyncIOScheduler(timezone=get_scheduler_timezone())
    scheduler.add_job(
        daily_refresh,
        "cron",
        id="daily_refresh",
        replace_existing=True,
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )
    scheduler.start()
    logger.info(f"Daily refresh scheduled: {REFRESH_CRON} ({SCHEDULER_TIMEZONE})")


# ---- Worker ----

async def worker_loop():
    """Main background worker that processes queued tasks."""
    global stop_flag, current_task_info, current_job_id
    while True:
        if stop_flag:
            await asyncio.sleep(1)
            continue
        try:
            job = await directus.get_next_job("fetch")
        except Exception as e:
            logger.warning(f"Could not poll fetch jobs: {e}")
            await asyncio.sleep(2)
            continue

        if not job:
            await asyncio.sleep(1)
            continue

        task = job.get("payload") or {}
        task_type = task.get("type")
        current_job_id = job["id"]
        try:
            await directus.update_job(job["id"], {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "error_message": None,
            })
            if task_type == "channel":
                await process_channel_task(task)
            elif task_type == "video":
                await process_single_video_task(task)
            elif task_type == "refresh":
                await process_refresh_task(task)
            elif task_type == "refresh_dates":
                await process_refresh_dates_task()
            else:
                raise ValueError(f"Unknown fetch job type: {task_type}")
            await directus.update_job(job["id"], {
                "status": "done",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except asyncio.CancelledError:
            await directus.update_job(job["id"], {
                "status": "cancelled",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_message": "Stopped by user",
            })
            raise
        except Exception as e:
            logger.error(f"Worker error on task {task}: {e}", exc_info=True)
            await directus.update_job(job["id"], {
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_message": str(e)[:1000],
            })
        finally:
            current_task_info = {}
            current_job_id = None


async def ai_worker_loop():
    """Background worker for AI notes so LLM calls do not block fetching."""
    global stop_flag, current_ai_task_info, current_ai_job_id
    while True:
        if stop_flag:
            await asyncio.sleep(1)
            continue
        try:
            job = await directus.get_next_job("ai")
        except Exception as e:
            logger.warning(f"Could not poll AI jobs: {e}")
            await asyncio.sleep(2)
            continue

        if not job:
            await asyncio.sleep(1)
            continue

        task = job.get("payload") or {}
        task_type = task.get("type")
        current_ai_job_id = job["id"]
        try:
            await directus.update_job(job["id"], {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "error_message": None,
            })
            if task_type == "ai_notes":
                await process_ai_notes_task(task)
            elif task_type == "ai_note_video":
                await process_single_ai_note_task(task)
            else:
                raise ValueError(f"Unknown AI job type: {task_type}")
            await directus.update_job(job["id"], {
                "status": "done",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except asyncio.CancelledError:
            await directus.update_job(job["id"], {
                "status": "cancelled",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_message": "Stopped by user",
            })
            raise
        except Exception as e:
            logger.error(f"AI worker error on task {task}: {e}", exc_info=True)
            await directus.update_job(job["id"], {
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_message": str(e)[:1000],
            })
        finally:
            current_ai_task_info = {}
            current_ai_job_id = None


async def process_channel_task(task: dict):
    """Process a channel: fetch video list + transcripts."""
    global current_task_info
    channel_url = task["channel_url"]
    channel_id = task.get("channel_id")

    current_task_info = {"type": "channel", "url": channel_url, "phase": "fetching video list"}

    # Update status
    if channel_id:
        await directus.update_channel(channel_id, {"status": "processing", "error_message": None})

    try:
        # Fetch video list (blocking, run in thread)
        loop = asyncio.get_event_loop()
        videos = await loop.run_in_executor(None, fetch_channel_videos, channel_url)

        if not videos:
            if channel_id:
                await directus.update_channel(channel_id, {
                    "status": "error",
                    "error_message": "No videos found or channel not accessible",
                })
            return

        # Get existing video IDs to avoid duplicates
        existing = {}
        if channel_id:
            existing_videos = await directus.get_videos_by_channel(channel_id)
            existing = {v["video_id"]: v for v in existing_videos}

        new_videos = [v for v in videos if v["video_id"] not in existing]
        logger.info(f"Channel {channel_url}: {len(videos)} total, {len(new_videos)} new")

        # Update video count
        if channel_id:
            await directus.update_channel(channel_id, {"video_count": len(videos)})

        # Backfill upload dates for already stored videos whenever the channel list has them.
        # This keeps regular channel refreshes from leaving old rows permanently date-less.
        if existing:
            by_video_id = {video["video_id"]: video for video in videos}
            backfilled = 0
            for yt_id, stored_video in existing.items():
                if stored_video.get("uploaded_at"):
                    continue
                uploaded_at = (by_video_id.get(yt_id) or {}).get("uploaded_at")
                if not uploaded_at:
                    continue
                await directus.update_video(stored_video["id"], {"uploaded_at": uploaded_at})
                backfilled += 1
            if backfilled:
                logger.info(f"Backfilled upload dates for {backfilled} existing videos")

        # Process each new video
        for i, video in enumerate(new_videos):
            if stop_flag:
                break

            current_task_info = {
                "type": "channel",
                "url": channel_url,
                "phase": f"transcript {i+1}/{len(new_videos)}",
                "video": video.get("title", video["video_id"]),
            }

            # Create video record as pending
            if not video.get("uploaded_at"):
                info = await loop.run_in_executor(None, fetch_video_info, video["video_id"])
                uploaded_at = parse_uploaded_at(info) if info else None
                if uploaded_at:
                    video["uploaded_at"] = uploaded_at
                    if not video.get("duration_seconds") and info.get("duration"):
                        video["duration_seconds"] = info.get("duration")
                    logger.info(f"Filled upload date for {video['video_id']}: {uploaded_at}")

            video_record = {**video, "channel_id": channel_id, "status": "pending"}
            created = await directus.create_video(video_record)
            directus_video_id = created.get("id")

            # Rate limit before fetching transcript (skip delay for first video)
            if i > 0:
                await rate_limited_sleep_transcript()

            # Fetch transcript
            transcript, transcript_timed = await asyncio.get_event_loop().run_in_executor(
                None, fetch_transcript_variants, video["video_id"]
            )

            update_data = {
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "status": "done" if transcript else "no_transcript",
                "transcript": transcript or "",
                "transcript_timed": transcript_timed or "",
            }
            if directus_video_id:
                await directus.update_video(directus_video_id, update_data)
                if transcript and AI_NOTES_AUTO:
                    await enqueue_ai_note(directus_video_id)

            logger.info(f"Video {video['video_id']}: {'done' if transcript else 'no_transcript'}")

        # Mark channel done
        if channel_id:
            await directus.update_channel(channel_id, {
                "status": "done",
                "last_refreshed": datetime.now(timezone.utc).isoformat(),
            })

    except Exception as e:
        logger.error(f"Error processing channel {channel_url}: {e}", exc_info=True)
        if channel_id:
            await directus.update_channel(channel_id, {
                "status": "error",
                "error_message": str(e)[:500],
            })


async def process_single_video_task(task: dict):
    """Process a single video URL."""
    global current_task_info
    video_url = task["video_url"]
    current_task_info = {"type": "video", "url": video_url, "phase": "fetching"}

    # Extract video ID from URL
    import re
    m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
    if not m:
        logger.error(f"Cannot extract video ID from: {video_url}")
        return

    yt_id = m.group(1)

    # Check if already exists
    existing = await directus.find_video_by_yt_id(yt_id)
    if existing and existing.get("transcript"):
        logger.info(f"Video {yt_id} already exists, skipping")
        return
    if existing:
        logger.info(f"Video {yt_id} already exists without transcript, retrying existing record")

    # Get video metadata via yt-dlp
    loop = asyncio.get_event_loop()

    info = await loop.run_in_executor(None, fetch_video_info, video_url)
    uploaded_at = parse_uploaded_at(info) if info else None

    # Resolve channel: use passed channel_id, or detect from yt-dlp metadata
    channel_id = task.get("channel_id") or (existing or {}).get("channel_id")
    if not channel_id and info:
        yt_channel_url = info.get("uploader_url") or info.get("channel_url") or ""
        yt_channel_name = info.get("channel") or info.get("uploader") or ""
        yt_channel_yt_id = info.get("channel_id") or ""
        if yt_channel_url or yt_channel_yt_id:
            handle = extract_handle_from_url(yt_channel_url) if yt_channel_url else yt_channel_yt_id
            existing_ch = await directus.find_channel_by_handle(handle)
            # Also try by YouTube channel ID (UCxxx) if handle lookup fails
            if not existing_ch and yt_channel_yt_id and yt_channel_yt_id != handle:
                existing_ch = await directus.find_channel_by_handle(yt_channel_yt_id)
            if existing_ch:
                channel_id = existing_ch["id"]
                logger.info(f"Single video {yt_id}: linked to existing channel {handle}")
            else:
                ch_record = await directus.create_channel({
                    "name": yt_channel_name or handle,
                    "channel_url": yt_channel_url,
                    "channel_handle": handle,
                    "status": "done",
                    "video_count": 0,
                })
                channel_id = ch_record.get("id")
                logger.info(f"Single video {yt_id}: created new channel {handle}")

    video_data = {
        "video_id": yt_id,
        "title": info.get("title") or (existing or {}).get("title") or yt_id,
        "url": video_url or (existing or {}).get("url"),
        "duration_seconds": info.get("duration") or (existing or {}).get("duration_seconds"),
        "uploaded_at": uploaded_at or (existing or {}).get("uploaded_at"),
        "channel_id": channel_id,
        "status": "pending",
    }
    if existing:
        directus_video_id = existing.get("id")
        await directus.update_video(directus_video_id, video_data)
    else:
        created = await directus.create_video(video_data)
        directus_video_id = created.get("id")

    # Fetch transcript
    transcript, transcript_timed = await loop.run_in_executor(None, fetch_transcript_variants, yt_id)

    update_data = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "status": "done" if transcript else "no_transcript",
        "transcript": transcript or "",
        "transcript_timed": transcript_timed or "",
    }
    if directus_video_id:
        await directus.update_video(directus_video_id, update_data)
        if transcript and AI_NOTES_AUTO:
            await enqueue_ai_note(directus_video_id)

    logger.info(f"Single video {yt_id}: {'done' if transcript else 'no_transcript'}")


async def process_refresh_task(task: dict):
    """Refresh a channel: fetch new videos only."""
    channel_id = task["channel_id"]
    channel = await directus.get_channel(channel_id)
    if not channel:
        return

    channel_url = channel.get("channel_url", "")
    if not channel_url:
        return

    await process_channel_task({
        "type": "channel",
        "channel_url": channel_url,
        "channel_id": channel_id,
    })


async def process_refresh_dates_task():
    """Fetch upload date for videos that are missing it."""
    global current_task_info
    videos = await directus.get_videos_missing_date()
    if not videos:
        logger.info("No videos with missing dates")
        return

    total = len(videos)
    logger.info(f"Refreshing dates for {total} videos")
    loop = asyncio.get_event_loop()

    updated = 0
    metadata_missing = 0
    date_missing = 0

    for i, video in enumerate(videos):
        if stop_flag:
            break

        yt_id = video["video_id"]
        current_task_info = {"type": "refresh_dates", "phase": f"{i+1}/{total}", "video": yt_id}

        info = await loop.run_in_executor(None, fetch_video_date_info, yt_id)
        if not info:
            logger.warning(f"No metadata available for {yt_id} (members-only/private/deleted/geo-blocked)")
            metadata_missing += 1
            continue

        uploaded_at = parse_uploaded_at(info)

        if uploaded_at:
            await directus.update_video(video["id"], {"uploaded_at": uploaded_at})
            logger.info(f"Updated date for {yt_id}: {uploaded_at}")
            updated += 1
        else:
            logger.warning(f"Metadata fetched but no parseable date for {yt_id}")
            date_missing += 1

    checked = updated + metadata_missing + date_missing
    logger.info(
        f"Date refresh complete: checked={checked} updated={updated} "
        f"metadata_missing={metadata_missing} date_missing={date_missing}"
    )


async def generate_and_store_ai_notes(directus_video_id: str, video: dict) -> bool:
    """Generate and persist AI notebook fields for a single Directus video."""
    global current_ai_task_info
    current_ai_task_info = {
        "type": "ai_note_video",
        "phase": "AI jegyzet generálása",
        "video_id": directus_video_id,
        "video": video.get("title") or video.get("video_id") or directus_video_id,
    }
    await directus.update_video(directus_video_id, {
        "ai_notes_status": "pending",
        "ai_notes_error": None,
    })
    try:
        notes = await generate_ai_notes(video)
        if not notes:
            await directus.update_video(directus_video_id, {
                "ai_notes_status": "error",
                "ai_notes_error": "No transcript available for AI notes",
            })
            return False

        await directus.update_video(directus_video_id, {
            **notes,
            "ai_notes_status": "done",
            "ai_notes_error": None,
            "ai_notes_generated_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"AI notes generated for {video.get('video_id') or directus_video_id}")
        return True
    except asyncio.CancelledError:
        logger.info(f"AI notes stopped for {video.get('video_id') or directus_video_id}")
        try:
            await asyncio.shield(directus.update_video(directus_video_id, {
                "ai_notes_status": "error",
                "ai_notes_error": "Stopped by user",
            }))
        except Exception as update_error:
            logger.warning(f"Could not persist stopped AI note status: {update_error}")
        raise
    except Exception as e:
        error_message = str(e) or repr(e)
        logger.warning(f"AI notes failed for {video.get('video_id') or directus_video_id}: {error_message}")
        await directus.update_video(directus_video_id, {
            "ai_notes_status": "error",
            "ai_notes_error": error_message[:1000],
        })
        return False


async def process_ai_notes_task(task: dict):
    """Generate AI notes for videos that have transcripts but no summary."""
    global current_ai_task_info
    limit = max(1, min(int(task.get("limit") or AI_NOTES_BATCH_LIMIT), 100))
    videos = await directus.get_videos_missing_ai_notes(limit)
    logger.info(f"Generating AI notes for {len(videos)} videos")

    done = 0
    failed = 0
    for i, video in enumerate(videos):
        if stop_flag:
            break
        current_ai_task_info = {
            "type": "ai_notes",
            "phase": f"{i+1}/{len(videos)}",
            "video_id": video.get("id"),
            "video": video.get("title") or video.get("video_id"),
        }
        ok = await generate_and_store_ai_notes(video["id"], video)
        if ok:
            done += 1
        else:
            failed += 1

    logger.info(f"AI notes batch complete: {done} done, {failed} failed")


async def process_single_ai_note_task(task: dict):
    """Generate AI notes for a selected video."""
    global current_ai_task_info
    video_id = task["video_id"]
    video = await directus.get_video(video_id)
    if not video:
        logger.warning(f"AI notes video not found: {video_id}")
        return
    if not (video.get("transcript") or video.get("transcript_timed")):
        await directus.update_video(video_id, {
            "ai_notes_status": "error",
            "ai_notes_error": "No transcript available for AI notes",
        })
        return

    current_ai_task_info = {
        "type": "ai_note_video",
        "phase": "generating",
        "video_id": video_id,
        "video": video.get("title") or video.get("video_id"),
    }
    await generate_and_store_ai_notes(video_id, video)


async def enqueue_ai_note(video_id: str):
    """Mark a video as queued for AI notes and enqueue it on the AI worker."""
    await directus.update_video(video_id, {
        "ai_notes_status": "pending",
        "ai_notes_error": None,
    })
    return await directus.create_job("ai", {"type": "ai_note_video", "video_id": video_id})


async def enqueue_fetch_job(task: dict, label: Optional[str] = None):
    """Create a persistent fetch job."""
    return await directus.create_job("fetch", task, label=label)


async def enqueue_ai_job(task: dict, label: Optional[str] = None):
    """Create a persistent AI job."""
    return await directus.create_job("ai", task, label=label)


async def clear_ai_notes(video_id: str) -> dict:
    """Remove generated AI notebook fields from a video without touching transcript data."""
    return await directus.update_video(video_id, {
        "summary": None,
        "topics": None,
        "takeaways": None,
        "questions": None,
        "obsidian_note": None,
        "ai_notes_status": None,
        "ai_notes_generated_at": None,
        "ai_notes_error": None,
    })


async def drain_queue(queue: asyncio.Queue, predicate=None) -> int:
    """Drain queued items. Return count of removed items."""
    removed = 0
    kept = []
    while not queue.empty():
        try:
            task = queue.get_nowait()
            if predicate is None or predicate(task):
                removed += 1
                queue.task_done()
            else:
                kept.append(task)
                queue.task_done()
        except asyncio.QueueEmpty:
            break
    for task in kept:
        await queue.put(task)
    return removed


async def cancel_jobs(queue: Optional[str] = None, predicate=None) -> int:
    """Mark queued/paused jobs as cancelled. Return count."""
    removed = 0
    for job in await directus.list_jobs():
        if queue and job.get("queue") != queue:
            continue
        if job.get("status") not in {"queued", "paused"}:
            continue
        task = job.get("payload") or {}
        if predicate and not predicate(task):
            continue
        await directus.update_job(job["id"], {
            "status": "cancelled",
            "finished_at": datetime.now(timezone.utc).isoformat(),
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
        return {**in_memory, "job_id": in_memory_job_id}
    running = await directus.get_running_job(queue)
    if not running:
        return {}
    payload = running.get("payload") or {}
    return {
        "type": running.get("type") or payload.get("type"),
        "phase": "running",
        "video": running.get("label"),
        "video_id": payload.get("video_id"),
        "job_id": running.get("id"),
    }


async def restart_ai_worker():
    """Cancel and recreate the AI worker."""
    global ai_worker_task
    if ai_worker_task and not ai_worker_task.done():
        ai_worker_task.cancel()
        try:
            await ai_worker_task
        except asyncio.CancelledError:
            pass
    ai_worker_task = asyncio.create_task(ai_worker_loop())


async def daily_refresh():
    """Automatically refresh all channels once a day."""
    logger.info("Starting daily channel refresh")
    channels = await directus.get_all_channels()
    for channel in channels:
        if channel.get("status") == "processing":
            continue
        await enqueue_fetch_job({"type": "refresh", "channel_id": channel["id"]})
        await rate_limited_sleep_channel()
    logger.info(f"Queued {len(channels)} channels for daily refresh")


# ---- App lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task, ai_worker_task, scheduler

    # Wait for Directus to be ready
    logger.info("Waiting for Directus...")
    for _ in range(40):
        if await directus.health_check():
            break
        await asyncio.sleep(3)
    else:
        logger.warning("Directus not responding, continuing anyway")

    # Bootstrap schema
    try:
        await directus.ensure_schema()
        cancelled = await directus.mark_stale_running_jobs_cancelled()
        if cancelled:
            logger.info(f"Marked {cancelled} stale running jobs as cancelled")
        await cleanup_orphan_ai_pending_videos()
    except Exception as e:
        logger.error(f"Schema bootstrap error: {e}", exc_info=True)
    await load_schedule_settings()

    # Start background worker
    worker_task = asyncio.create_task(worker_loop())
    ai_worker_task = asyncio.create_task(ai_worker_loop())

    # Start scheduler for daily refresh
    start_refresh_scheduler()

    yield

    # Cleanup
    if worker_task:
        worker_task.cancel()
    if ai_worker_task:
        ai_worker_task.cancel()
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="YouTube Transcript Fetcher", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- API Models ----

class FetchChannelsRequest(BaseModel):
    urls: list[str]


class FetchVideoRequest(BaseModel):
    url: str
    channel_id: Optional[str] = None


class ScheduleRequest(BaseModel):
    cron: str
    timezone: str


class AiNotesRequest(BaseModel):
    limit: int = AI_NOTES_BATCH_LIMIT


class ChannelAiNotesRequest(BaseModel):
    limit: int = 500


class JobMoveRequest(BaseModel):
    direction: str


# ---- API Endpoints ----

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "queue_size": await directus.count_jobs("fetch", "queued"),
        "ai_queue_size": await directus.count_jobs("ai", "queued"),
        "fetch_active_size": await directus.count_jobs("fetch", "queued,running,paused"),
        "ai_active_size": await directus.count_jobs("ai", "queued,running,paused"),
    }


@app.get("/status")
async def status():
    fetch_current = await current_job_snapshot("fetch", current_task_info, current_job_id)
    ai_current = await current_job_snapshot("ai", current_ai_task_info, current_ai_job_id)
    return {
        "queue_size": await directus.count_jobs("fetch", "queued"),
        "ai_queue_size": await directus.count_jobs("ai", "queued"),
        "fetch_active_size": await directus.count_jobs("fetch", "queued,running,paused"),
        "ai_active_size": await directus.count_jobs("ai", "queued,running,paused"),
        "stop_flag": stop_flag,
        "current_task": fetch_current,
        "current_ai_task": ai_current,
        "schedule": {
            "cron": REFRESH_CRON,
            "timezone": SCHEDULER_TIMEZONE,
        },
    }


@app.get("/jobs")
async def list_jobs():
    jobs = await directus.list_jobs()
    return {
        "jobs": jobs,
        "counts": {
            "fetch": await directus.count_jobs("fetch", "queued"),
            "ai": await directus.count_jobs("ai", "queued"),
        },
        "current": {
            "fetch": current_job_id,
            "ai": current_ai_job_id,
        },
    }


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
    global worker_task, ai_worker_task
    job = await directus.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cancelled_current = False
    if job_id == current_job_id and worker_task and not worker_task.done():
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        worker_task = asyncio.create_task(worker_loop())
        cancelled_current = True
    if job_id == current_ai_job_id and ai_worker_task and not ai_worker_task.done():
        await restart_ai_worker()
        cancelled_current = True

    await directus.delete_job(job_id)
    return {"deleted": True, "job_id": job_id, "cancelled_current": cancelled_current}


@app.get("/schedule")
async def get_schedule():
    return {"cron": REFRESH_CRON, "timezone": SCHEDULER_TIMEZONE}


@app.patch("/schedule")
async def update_schedule(request: ScheduleRequest):
    global REFRESH_CRON, SCHEDULER_TIMEZONE
    cron = request.cron.strip()
    timezone_name = request.timezone.strip()
    try:
        validate_schedule(cron, timezone_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    REFRESH_CRON = cron
    SCHEDULER_TIMEZONE = timezone_name
    start_refresh_scheduler()
    await save_schedule_settings(cron, timezone_name)
    return {"cron": REFRESH_CRON, "timezone": SCHEDULER_TIMEZONE}


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
    """Manually refresh a channel (fetch new videos)."""
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


@app.post("/ai-notes")
async def ai_notes(request: AiNotesRequest):
    """Queue AI note generation for videos that have transcripts but no summary."""
    limit = max(1, min(request.limit, 100))
    await enqueue_ai_job({"type": "ai_notes", "limit": limit})
    return {"queued": True, "limit": limit}


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
    global ai_worker_task
    video = await directus.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    removed = await cancel_jobs(
        "ai",
        lambda task: task.get("type") == "ai_note_video" and task.get("video_id") == video_id,
    )
    cancelled_current = False
    if current_ai_task_info.get("video_id") == video_id and ai_worker_task and not ai_worker_task.done():
        await restart_ai_worker()
        cancelled_current = True
    await clear_ai_notes(video_id)
    return {"deleted": True, "video_id": video_id, "removed": removed, "cancelled_current": cancelled_current}


@app.post("/stop")
async def stop_processing():
    """Clear the task queue, cancel current processing, then keep the worker ready."""
    global stop_flag, worker_task, ai_worker_task
    stop_flag = True
    cancelled_current = False
    cancelled_ai_current = False

    if worker_task and not worker_task.done():
        worker_task.cancel()
        cancelled_current = True
    if ai_worker_task and not ai_worker_task.done():
        ai_worker_task.cancel()
        cancelled_ai_current = True

    # Cancel queued persistent jobs
    drained = await cancel_jobs("fetch")
    ai_drained = await cancel_jobs("ai")

    stop_flag = False
    worker_task = asyncio.create_task(worker_loop())
    ai_worker_task = asyncio.create_task(ai_worker_loop())
    return {
        "stopped": True,
        "drained": drained,
        "ai_drained": ai_drained,
        "cancelled_current": cancelled_current,
        "cancelled_ai_current": cancelled_ai_current,
    }


@app.post("/resume")
async def resume_processing():
    """Resume processing after stop."""
    global stop_flag, worker_task, ai_worker_task
    stop_flag = False
    if not worker_task or worker_task.done():
        worker_task = asyncio.create_task(worker_loop())
    if not ai_worker_task or ai_worker_task.done():
        ai_worker_task = asyncio.create_task(ai_worker_loop())
    return {"resumed": True}
