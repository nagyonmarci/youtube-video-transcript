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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import pg_client
from transcriber import MembersOnlyError, transcribe_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


APP_API_TOKEN = required_env("APP_API_TOKEN")
APP_CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("APP_CORS_ORIGINS", "http://yt.test,http://localhost:4321").split(",")
    if origin.strip()
]
WHISPER_MODEL_PATH = os.environ.get("WHISPER_MODEL_PATH", "/app/models/ggml-large-v3.bin")
WHISPER_THREADS = int(os.environ.get("WHISPER_THREADS", "4"))
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "auto")
BATCH_CRON = os.environ.get("BATCH_CRON", "0 3 * * *")
BATCH_LIMIT = int(os.environ.get("BATCH_LIMIT", "50"))
WHISPER_MAX_ATTEMPTS = int(os.environ.get("WHISPER_MAX_ATTEMPTS", "3"))

# Rate limiting between audio downloads (same as fetcher)
DOWNLOAD_DELAY_MIN = 45
DOWNLOAD_DELAY_MAX = 75

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
    await pg_client.update_video(directus_id, {"whisper_status": "processing"})

    # Rate limit before download (skip for first item in batch)
    if task.get("delay", False):
        delay = random.uniform(DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX)
        logger.info(f"Rate limiting: sleeping {delay:.1f}s before download")
        await asyncio.sleep(delay)

    # Run transcription in thread pool (blocking I/O)
    current_task_info["phase"] = "transcribing"
    loop = asyncio.get_event_loop()
    now = datetime.now(timezone.utc)
    try:
        transcript_result = await loop.run_in_executor(
            None,
            transcribe_video,
            video_id,
            duration,
            WHISPER_MODEL_PATH,
            WHISPER_LANGUAGE,
            WHISPER_THREADS,
        )
    except MembersOnlyError:
        await pg_client.update_video(directus_id, {
            "whisper_status": "members_only",
            "processed_at": now,
        })
        logger.info(f"Members-only video, skipped: {video_id}")
        return

    if transcript_result:
        transcript, transcript_timed = transcript_result
        await pg_client.update_video(directus_id, {
            "transcript": transcript,
            "transcript_timed": transcript_timed,
            "status": "done",
            "whisper_status": "done",
            "processed_at": now,
        })
        logger.info(f"Whisper done: {video_id} ({len(transcript)} chars)")
    else:
        attempts = int(video.get("whisper_attempts") or 0) + 1
        await pg_client.update_video(directus_id, {
            "whisper_status": "error",
            "whisper_attempts": attempts,
            "processed_at": now,
        })
        logger.warning(f"Whisper failed: {video_id} (attempt {attempts}/{WHISPER_MAX_ATTEMPTS})")


async def run_batch(limit: int = BATCH_LIMIT, language: str = WHISPER_LANGUAGE):
    """Fetch no_transcript videos and queue them for whisper processing."""
    global batch_running
    if batch_running:
        logger.info("Batch already running, skipping")
        return 0

    batch_running = True
    try:
        videos = await pg_client.get_no_transcript_videos(limit=limit, max_attempts=WHISPER_MAX_ATTEMPTS)
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

    # Wait for Postgres
    logger.info("Waiting for Postgres...")
    for _ in range(40):
        try:
            pool = await pg_client.get_pg_pool()
            await pool.fetchval("SELECT 1")
            break
        except Exception:
            await asyncio.sleep(3)
    else:
        logger.warning("Postgres not responding, continuing anyway")

    # Pre-mark known members-only videos (title contains MEMBERS) — redundant fallback,
    # the fetcher's for_whisper flag already excludes members-only videos more reliably.
    try:
        count = await pg_client.mark_members_only_videos()
        if count:
            logger.info(f"Pre-marked {count} MEMBERS videos as members_only")
    except Exception as e:
        logger.warning(f"Could not pre-mark members-only videos: {e}")

    # Reset any stale "processing" states from previous crashes
    try:
        reset_count = await pg_client.reset_stale_processing()
        if reset_count:
            logger.info(f"Reset {reset_count} stale whisper_status=processing records")
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
    await pg_client.close_pg_pool()


app = FastAPI(title="Whisper Transcription Service", lifespan=lifespan)


@app.middleware("http")
async def require_app_token(request: Request, call_next):
    if APP_API_TOKEN and request.url.path not in {"/health"}:
        if request.headers.get("x-app-token") != APP_API_TOKEN:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_CORS_ORIGINS,
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
    video = await pg_client.find_video_by_yt_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

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
