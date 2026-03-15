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

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from directus_client import DirectusClient
from youtube_fetcher import (
    fetch_channel_videos,
    fetch_channel_name,
    fetch_transcript,
    parse_channel_input,
    extract_handle_from_url,
    rate_limited_sleep_transcript,
    rate_limited_sleep_channel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055")
DIRECTUS_TOKEN = os.environ.get("DIRECTUS_TOKEN", "admin-token-change-me")
REFRESH_CRON = os.environ.get("REFRESH_CRON", "0 2 * * *")

directus = DirectusClient(DIRECTUS_URL, DIRECTUS_TOKEN)

# Worker state
task_queue: asyncio.Queue = asyncio.Queue()
worker_task: Optional[asyncio.Task] = None
stop_flag = False
current_task_info: dict = {}
scheduler: Optional[AsyncIOScheduler] = None


# ---- Worker ----

async def worker_loop():
    """Main background worker that processes queued tasks."""
    global stop_flag, current_task_info
    while True:
        try:
            task = await asyncio.wait_for(task_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if stop_flag:
            task_queue.task_done()
            continue

        task_type = task.get("type")
        try:
            if task_type == "channel":
                await process_channel_task(task)
            elif task_type == "video":
                await process_single_video_task(task)
            elif task_type == "refresh":
                await process_refresh_task(task)
        except Exception as e:
            logger.error(f"Worker error on task {task}: {e}", exc_info=True)
        finally:
            task_queue.task_done()
            current_task_info = {}


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
        existing = set()
        if channel_id:
            existing_videos = await directus.get_videos_by_channel(channel_id)
            existing = {v["video_id"] for v in existing_videos}

        new_videos = [v for v in videos if v["video_id"] not in existing]
        logger.info(f"Channel {channel_url}: {len(videos)} total, {len(new_videos)} new")

        # Update video count
        if channel_id:
            await directus.update_channel(channel_id, {"video_count": len(videos)})

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
            video_record = {**video, "channel_id": channel_id, "status": "pending"}
            created = await directus.create_video(video_record)
            directus_video_id = created.get("id")

            # Rate limit before fetching transcript (skip delay for first video)
            if i > 0:
                await rate_limited_sleep_transcript()

            # Fetch transcript
            transcript = await asyncio.get_event_loop().run_in_executor(
                None, fetch_transcript, video["video_id"]
            )

            update_data = {
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "status": "done" if transcript else "no_transcript",
                "transcript": transcript or "",
            }
            if directus_video_id:
                await directus.update_video(directus_video_id, update_data)

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
    if existing:
        logger.info(f"Video {yt_id} already exists, skipping")
        return

    # Get video metadata via yt-dlp
    loop = asyncio.get_event_loop()

    import subprocess, json as json_mod
    def get_video_info():
        cmd = ["yt-dlp", "--dump-json", "--no-warnings", "--skip-download", video_url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.stdout:
                return json_mod.loads(result.stdout)
        except Exception:
            pass
        return {}

    info = await loop.run_in_executor(None, get_video_info)

    from datetime import datetime as dt
    upload_date = info.get("upload_date", "")
    uploaded_at = None
    if len(upload_date) == 8:
        try:
            uploaded_at = dt(int(upload_date[:4]), int(upload_date[4:6]), int(upload_date[6:8]),
                              tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass

    video_data = {
        "video_id": yt_id,
        "title": info.get("title", yt_id),
        "url": video_url,
        "duration_seconds": info.get("duration"),
        "uploaded_at": uploaded_at,
        "channel_id": task.get("channel_id"),
        "status": "pending",
    }
    created = await directus.create_video(video_data)
    directus_video_id = created.get("id")

    # Fetch transcript
    transcript = await loop.run_in_executor(None, fetch_transcript, yt_id)

    update_data = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "status": "done" if transcript else "no_transcript",
        "transcript": transcript or "",
    }
    if directus_video_id:
        await directus.update_video(directus_video_id, update_data)

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


async def daily_refresh():
    """Automatically refresh all channels once a day."""
    logger.info("Starting daily channel refresh")
    channels = await directus.get_all_channels()
    for channel in channels:
        if channel.get("status") == "processing":
            continue
        await task_queue.put({"type": "refresh", "channel_id": channel["id"]})
        await rate_limited_sleep_channel()
    logger.info(f"Queued {len(channels)} channels for daily refresh")


# ---- App lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task, scheduler

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
    except Exception as e:
        logger.error(f"Schema bootstrap error: {e}", exc_info=True)

    # Start background worker
    worker_task = asyncio.create_task(worker_loop())

    # Start scheduler for daily refresh
    scheduler = AsyncIOScheduler()
    cron_parts = REFRESH_CRON.split()
    if len(cron_parts) == 5:
        minute, hour, day, month, day_of_week = cron_parts
        scheduler.add_job(
            daily_refresh,
            "cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
    scheduler.start()
    logger.info(f"Daily refresh scheduled: {REFRESH_CRON}")

    yield

    # Cleanup
    if worker_task:
        worker_task.cancel()
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


# ---- API Endpoints ----

@app.get("/health")
async def health():
    return {"status": "ok", "queue_size": task_queue.qsize()}


@app.get("/status")
async def status():
    return {
        "queue_size": task_queue.qsize(),
        "stop_flag": stop_flag,
        "current_task": current_task_info,
    }


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
            await task_queue.put({"type": "refresh", "channel_id": channel_id})
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
            await task_queue.put({
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

    await task_queue.put({
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

    await task_queue.put({"type": "refresh", "channel_id": channel_id})
    return {"queued": True, "channel_id": channel_id}


@app.post("/stop")
async def stop_processing():
    """Clear the task queue and stop current processing."""
    global stop_flag
    stop_flag = True

    # Drain queue
    drained = 0
    while not task_queue.empty():
        try:
            task_queue.get_nowait()
            task_queue.task_done()
            drained += 1
        except asyncio.QueueEmpty:
            break

    return {"stopped": True, "drained": drained}


@app.post("/resume")
async def resume_processing():
    """Resume processing after stop."""
    global stop_flag
    stop_flag = False
    return {"resumed": True}
