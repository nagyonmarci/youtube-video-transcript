"""
Whisper Transcription Service
Batch-processes YouTube videos that have no text-based transcript
using whisper.cpp speech recognition.
"""

import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from directus_client import DirectusClient
from transcriber import transcribe_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055")
DIRECTUS_TOKEN = os.environ.get("DIRECTUS_TOKEN", "admin-token-change-me")
WHISPER_MODEL_PATH = os.environ.get("WHISPER_MODEL_PATH", "/app/models/ggml-large-v3.bin")
WHISPER_THREADS = int(os.environ.get("WHISPER_THREADS", "4"))
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "auto")
BATCH_CRON = os.environ.get("BATCH_CRON", "0 3 * * *")
BATCH_LIMIT = int(os.environ.get("BATCH_LIMIT", "50"))

# Rate limiting between audio downloads (same as fetcher)
DOWNLOAD_DELAY_MIN = 45
DOWNLOAD_DELAY_MAX = 75

directus = DirectusClient(DIRECTUS_URL, DIRECTUS_TOKEN)

# Worker state
task_queue: asyncio.Queue = asyncio.Queue()
worker_task: Optional[asyncio.Task] = None
stop_flag = False
current_task_info: dict = {}
batch_running = False
scheduler: Optional[AsyncIOScheduler] = None


# ---- Worker ----

async def worker_loop():
    """Background worker that processes queued transcription tasks."""
    global stop_flag, current_task_info
    while True:
        try:
            task = await asyncio.wait_for(task_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if stop_flag:
            task_queue.task_done()
            continue

        try:
            await process_transcription_task(task)
        except Exception as e:
            logger.error(f"Worker error on task {task}: {e}", exc_info=True)
        finally:
            task_queue.task_done()
            current_task_info = {}


async def process_transcription_task(task: dict):
    """Download audio, transcribe with whisper, update Directus."""
    global current_task_info
    video = task["video"]
    directus_id = video["id"]
    video_id = video["video_id"]
    duration = video.get("duration_seconds") or 0

    current_task_info = {
        "video_id": video_id,
        "title": video.get("title", ""),
        "phase": "downloading",
    }

    # Mark as processing
    await directus.update_video(directus_id, {"whisper_status": "processing"})

    # Rate limit before download (skip for first item in batch)
    if task.get("delay", False):
        delay = random.uniform(DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX)
        logger.info(f"Rate limiting: sleeping {delay:.1f}s before download")
        await asyncio.sleep(delay)

    # Run transcription in thread pool (blocking I/O)
    current_task_info["phase"] = "transcribing"
    loop = asyncio.get_event_loop()
    transcript = await loop.run_in_executor(
        None,
        transcribe_video,
        video_id,
        duration,
        WHISPER_MODEL_PATH,
        WHISPER_LANGUAGE,
        WHISPER_THREADS,
    )

    now = datetime.now(timezone.utc).isoformat()
    if transcript:
        await directus.update_video(directus_id, {
            "transcript": transcript,
            "status": "done",
            "whisper_status": "done",
            "processed_at": now,
        })
        logger.info(f"Whisper done: {video_id} ({len(transcript)} chars)")
    else:
        await directus.update_video(directus_id, {
            "whisper_status": "error",
            "processed_at": now,
        })
        logger.warning(f"Whisper failed: {video_id}")


async def run_batch(limit: int = BATCH_LIMIT, language: str = WHISPER_LANGUAGE):
    """Fetch no_transcript videos and queue them for whisper processing."""
    global batch_running
    if batch_running:
        logger.info("Batch already running, skipping")
        return 0

    batch_running = True
    try:
        videos = await directus.get_no_transcript_videos(limit=limit)
        if not videos:
            logger.info("No videos to transcribe")
            return 0

        logger.info(f"Queueing {len(videos)} videos for whisper transcription")
        for i, video in enumerate(videos):
            await task_queue.put({
                "video": video,
                "language": language,
                "delay": i > 0,
            })
        return len(videos)
    finally:
        batch_running = False


async def scheduled_batch():
    """Cron-triggered batch run."""
    logger.info("Starting scheduled whisper batch")
    count = await run_batch()
    logger.info(f"Scheduled batch queued {count} videos")


# ---- App lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task, scheduler

    # Wait for Directus
    logger.info("Waiting for Directus...")
    for _ in range(40):
        if await directus.health_check():
            break
        await asyncio.sleep(3)
    else:
        logger.warning("Directus not responding, continuing anyway")

    # Ensure whisper_status field exists
    try:
        await directus.ensure_whisper_fields()
    except Exception as e:
        logger.error(f"Schema bootstrap error: {e}", exc_info=True)

    # Reset any stale "processing" states from previous crashes
    try:
        from httpx import AsyncClient
        params = "?filter[whisper_status][_eq]=processing&limit=-1&fields=id"
        result = await directus._request("GET", f"/items/videos{params}")
        stale = result.get("data", [])
        for v in stale:
            await directus.update_video(v["id"], {"whisper_status": None})
        if stale:
            logger.info(f"Reset {len(stale)} stale whisper_status=processing records")
    except Exception as e:
        logger.warning(f"Could not reset stale records: {e}")

    # Start worker
    worker_task = asyncio.create_task(worker_loop())

    # Start scheduler
    scheduler = AsyncIOScheduler()
    cron_parts = BATCH_CRON.split()
    if len(cron_parts) == 5:
        minute, hour, day, month, day_of_week = cron_parts
        scheduler.add_job(
            scheduled_batch,
            "cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
    scheduler.start()
    logger.info(f"Whisper batch scheduled: {BATCH_CRON}")

    yield

    if worker_task:
        worker_task.cancel()
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Whisper Transcription Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- API Models ----

class BatchRequest(BaseModel):
    limit: int = BATCH_LIMIT
    language: str = WHISPER_LANGUAGE


# ---- API Endpoints ----

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "queue_size": task_queue.qsize(),
        "model": WHISPER_MODEL_PATH,
    }


@app.get("/status")
async def status():
    return {
        "queue_size": task_queue.qsize(),
        "stop_flag": stop_flag,
        "batch_running": batch_running,
        "current_task": current_task_info,
    }


@app.post("/transcribe-batch")
async def transcribe_batch(request: BatchRequest = BatchRequest()):
    """Trigger a batch transcription of no_transcript videos."""
    count = await run_batch(limit=request.limit, language=request.language)
    return {"queued": count}


@app.post("/transcribe-video/{video_id}")
async def transcribe_single_video(video_id: str):
    """Transcribe a single video by its YouTube video ID."""
    video = await directus.find_video_by_yt_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found in Directus")

    await task_queue.put({
        "video": video,
        "language": WHISPER_LANGUAGE,
        "delay": False,
    })
    return {"queued": True, "video_id": video_id}


@app.post("/stop")
async def stop_processing():
    """Stop processing and drain the queue."""
    global stop_flag
    stop_flag = True
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
