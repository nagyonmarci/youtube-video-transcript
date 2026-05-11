"""
YouTube Transcript Fetcher Service
FastAPI microservice that fetches YouTube channel/video transcripts
and stores them in Directus CMS.
"""

import asyncio
import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import asyncpg
import httpx

from ai_notes import configure_ai_notes, generate_ai_notes
from constants import (
    HEARTBEAT_INTERVAL, WORKER_IDLE_SLEEP, WORKER_POLL_BACKOFF,
    STREAM_UPDATE_INTERVAL, BOOTSTRAP_CHECK_INTERVAL, IDLE_SLEEP,
    STOPPED_BY_USER,
    QUEUE_FETCH, QUEUE_AI,
)
from directus_client import DirectusClient, now_iso
from youtube_fetcher import (
    fetch_channel_videos,
    fetch_channel_name,
    fetch_video_info,
    fetch_video_date_info,
    fetch_transcript_variants,
    parse_uploaded_at,
    best_thumbnail_url,
    is_members_only_video,
    youtube_thumbnail_url,
    parse_channel_input,
    extract_handle_from_url,
    rate_limited_sleep_transcript,
    rate_limited_sleep_channel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055")
DIRECTUS_TOKEN = required_env("DIRECTUS_TOKEN")
APP_API_TOKEN = required_env("APP_API_TOKEN")
APP_CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("APP_CORS_ORIGINS", "http://yt.test,http://localhost:4321").split(",")
    if origin.strip()
]
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "directus")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "directus")
POSTGRES_PASSWORD = required_env("POSTGRES_PASSWORD")
REFRESH_CRON = os.environ.get("REFRESH_CRON", "0 7 * * *")
SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Europe/Budapest")
AI_NOTES_AUTO = os.environ.get("AI_NOTES_AUTO", "false").lower() in {"1", "true", "yes", "on"}
AI_NOTES_BATCH_LIMIT = int(os.environ.get("AI_NOTES_BATCH_LIMIT", "10"))
AI_NOTES_MAX_BATCH_LIMIT = int(os.environ.get("AI_NOTES_MAX_BATCH_LIMIT", "20000"))
AI_NOTES_YEAR_BACKFILL_ENABLED = os.environ.get("AI_NOTES_YEAR_BACKFILL_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
AI_NOTES_YEAR_BACKFILL_YEAR = int(os.environ.get("AI_NOTES_YEAR_BACKFILL_YEAR", "2026"))
AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT = max(1, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT", "50")))
AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE = max(1, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE", "100")))
AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS = max(30, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS", "300")))
AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS = max(10, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS", "60")))
AI_NOTES_WORKER_ENABLED = os.environ.get("AI_NOTES_WORKER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
AI_NOTES_JOB_COOLDOWN_SECONDS = max(0, int(os.environ.get("AI_NOTES_JOB_COOLDOWN_SECONDS", "0")))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:31b-mlx-bf16")
AI_NOTES_MAX_CHARS = int(os.environ.get("AI_NOTES_MAX_CHARS", "45000"))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))
FETCHER_ROLE = os.environ.get("FETCHER_ROLE", "all").lower()
WORKER_QUEUES = {item.strip() for item in os.environ.get("WORKER_QUEUES", "fetch,ai").split(",") if item.strip()}
FETCH_WORKER_CONCURRENCY = max(0, int(os.environ.get("FETCH_WORKER_CONCURRENCY", "1")))
AI_WORKER_CONCURRENCY = max(0, int(os.environ.get("AI_WORKER_CONCURRENCY", "1")))
STALE_JOB_MINUTES = max(5, int(os.environ.get("STALE_JOB_MINUTES", "30")))
JOB_CLEANUP_DAYS = int(os.environ.get("JOB_CLEANUP_DAYS", "7"))
WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"

directus = DirectusClient(DIRECTUS_URL, DIRECTUS_TOKEN)
pg_pool: Optional[asyncpg.Pool] = None

# Worker state
worker_task: Optional[asyncio.Task] = None
ai_worker_task: Optional[asyncio.Task] = None
stop_flag = False
current_task_info: dict = {}
current_ai_task_info: dict = {}
current_job_id: Optional[str] = None
current_ai_job_id: Optional[str] = None
scheduler: Optional[AsyncIOScheduler] = None
current_job_id_var: ContextVar[Optional[str]] = ContextVar("current_job_id", default=None)
current_job_queue_var: ContextVar[Optional[str]] = ContextVar("current_job_queue", default=None)
current_task_info_var: ContextVar[dict] = ContextVar("current_task_info", default={})
last_ai_year_backfill_attempt = 0.0
last_runtime_settings_load = 0.0
last_stale_job_reset = 0.0
AI_NOTE_GENERATED_FIELDS = {
    "summary",
    "topics",
    "takeaways",
    "questions",
    "obsidian_note",
    "study_guide",
    "critique",
}


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


def bool_setting(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def int_setting(value, default: int, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def current_app_settings() -> dict:
    return {
        "ollama_base_url": OLLAMA_BASE_URL,
        "ollama_chat_model": OLLAMA_CHAT_MODEL,
        "ollama_timeout": OLLAMA_TIMEOUT,
        "ai_notes_max_chars": AI_NOTES_MAX_CHARS,
        "ai_notes_auto": AI_NOTES_AUTO,
        "ai_notes_batch_limit": AI_NOTES_BATCH_LIMIT,
        "ai_notes_max_batch_limit": AI_NOTES_MAX_BATCH_LIMIT,
        "ai_notes_year_backfill_enabled": AI_NOTES_YEAR_BACKFILL_ENABLED,
        "ai_notes_year_backfill_year": AI_NOTES_YEAR_BACKFILL_YEAR,
        "ai_notes_year_backfill_batch_limit": AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        "ai_notes_year_backfill_target_active": AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
        "ai_notes_year_backfill_interval_seconds": AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
        "ai_notes_year_backfill_idle_seconds": AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS,
        "ai_notes_worker_enabled": AI_NOTES_WORKER_ENABLED,
        "ai_notes_job_cooldown_seconds": AI_NOTES_JOB_COOLDOWN_SECONDS,
    }


def apply_app_settings(settings: dict) -> None:
    global OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_TIMEOUT, AI_NOTES_MAX_CHARS
    global AI_NOTES_AUTO, AI_NOTES_BATCH_LIMIT, AI_NOTES_MAX_BATCH_LIMIT
    global AI_NOTES_YEAR_BACKFILL_ENABLED, AI_NOTES_YEAR_BACKFILL_YEAR
    global AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT, AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE
    global AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS, AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS
    global AI_NOTES_WORKER_ENABLED, AI_NOTES_JOB_COOLDOWN_SECONDS

    OLLAMA_BASE_URL = str(settings.get("ollama_base_url") or OLLAMA_BASE_URL).strip().rstrip("/")
    OLLAMA_CHAT_MODEL = str(settings.get("ollama_chat_model") or OLLAMA_CHAT_MODEL).strip()
    OLLAMA_TIMEOUT = int_setting(settings.get("ollama_timeout"), OLLAMA_TIMEOUT, 30)
    AI_NOTES_MAX_CHARS = int_setting(settings.get("ai_notes_max_chars"), AI_NOTES_MAX_CHARS, 1000)
    AI_NOTES_AUTO = bool_setting(settings.get("ai_notes_auto", AI_NOTES_AUTO))
    AI_NOTES_BATCH_LIMIT = int_setting(settings.get("ai_notes_batch_limit"), AI_NOTES_BATCH_LIMIT, 1)
    AI_NOTES_MAX_BATCH_LIMIT = int_setting(settings.get("ai_notes_max_batch_limit"), AI_NOTES_MAX_BATCH_LIMIT, 1)
    AI_NOTES_YEAR_BACKFILL_ENABLED = bool_setting(settings.get("ai_notes_year_backfill_enabled", AI_NOTES_YEAR_BACKFILL_ENABLED))
    AI_NOTES_YEAR_BACKFILL_YEAR = int_setting(settings.get("ai_notes_year_backfill_year"), AI_NOTES_YEAR_BACKFILL_YEAR, 2005)
    AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT = int_setting(settings.get("ai_notes_year_backfill_batch_limit"), AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT, 1)
    AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE = int_setting(settings.get("ai_notes_year_backfill_target_active"), AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE, 1)
    AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS = int_setting(settings.get("ai_notes_year_backfill_interval_seconds"), AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS, 30)
    AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS = int_setting(settings.get("ai_notes_year_backfill_idle_seconds"), AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS, 10)
    AI_NOTES_WORKER_ENABLED = bool_setting(settings.get("ai_notes_worker_enabled", AI_NOTES_WORKER_ENABLED))
    AI_NOTES_JOB_COOLDOWN_SECONDS = int_setting(settings.get("ai_notes_job_cooldown_seconds"), AI_NOTES_JOB_COOLDOWN_SECONDS, 0, 3600)
    configure_ai_notes(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_CHAT_MODEL,
        max_chars=AI_NOTES_MAX_CHARS,
        timeout=OLLAMA_TIMEOUT,
    )


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


async def load_app_settings():
    global last_runtime_settings_load
    settings = current_app_settings()
    try:
        stored = {}
        for key in settings.keys():
            value = await directus.get_setting(key)
            if value is not None:
                stored[key] = value
        apply_app_settings({**settings, **stored})
        last_runtime_settings_load = time.monotonic()
    except Exception as e:
        logger.warning(f"Could not load app settings, using current values: {e}")


async def refresh_app_settings_if_due(max_age_seconds: int = 30, force: bool = False):
    if force or time.monotonic() - last_runtime_settings_load >= max_age_seconds:
        await load_app_settings()


async def get_ollama_resource_status() -> dict:
    result = {
        "online": False,
        "base_url": OLLAMA_BASE_URL,
        "configured_model": OLLAMA_CHAT_MODEL,
        "models": [],
        "sampled_at": now_iso(),
        "error": None,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0)) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
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
        "ai_worker_enabled": AI_NOTES_WORKER_ENABLED,
        "ai_job_cooldown_seconds": AI_NOTES_JOB_COOLDOWN_SECONDS,
        "ai_worker_concurrency": AI_WORKER_CONCURRENCY,
        "ai_queue": ai_counts,
        "ollama": await get_ollama_resource_status(),
    }


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


async def get_pg_pool() -> asyncpg.Pool:
    global pg_pool
    if pg_pool:
        return pg_pool
    pg_pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        min_size=1,
        max_size=max(4, FETCH_WORKER_CONCURRENCY + AI_WORKER_CONCURRENCY + 2),
    )
    return pg_pool


async def close_pg_pool():
    global pg_pool
    if pg_pool:
        await pg_pool.close()
        pg_pool = None


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
    scheduler.add_job(
        cleanup_old_jobs,
        "interval",
        hours=24,
        id="cleanup_old_jobs",
        replace_existing=True,
    )
    if AI_NOTES_AUTO and AI_NOTES_YEAR_BACKFILL_ENABLED:
        scheduler.add_job(
            maybe_enqueue_ai_year_backfill,
            "interval",
            seconds=AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
            id="ai_year_backfill",
            kwargs={"source": "scheduler"},
            next_run_time=datetime.now(get_scheduler_timezone()),
            replace_existing=True,
        )
    scheduler.start()
    logger.info(f"Daily refresh scheduled: {REFRESH_CRON} ({SCHEDULER_TIMEZONE})")
    if AI_NOTES_AUTO and AI_NOTES_YEAR_BACKFILL_ENABLED:
        logger.info(
            "AI year backfill scheduled: year=%s interval=%ss target_active=%s batch=%s",
            AI_NOTES_YEAR_BACKFILL_YEAR,
            AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
            AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        )


# ---- Reliability helpers ----

def job_dedupe_key(queue: str, task: dict) -> str:
    """Stable key for jobs that should not be queued more than once while active."""
    task_type = task.get("type") or "job"
    if task_type in {"ai_notes", "refresh_dates", "refresh_thumbnails"}:
        return f"{queue}:{task_type}"
    if task_type == "ai_note_video":
        return f"{queue}:{task_type}:{task.get('video_id') or ''}"
    if task_type in {"channel", "refresh"}:
        return f"{queue}:{task_type}:{task.get('channel_id') or task.get('channel_url') or ''}"
    if task_type == "video":
        return f"{queue}:{task_type}:{task.get('video_url') or ''}"
    encoded = json.dumps(task, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"{queue}:{task_type}:{encoded}"[:512]


async def update_job_progress(queue: str, current: int, total: int, label: Optional[str] = None):
    job_id = current_job_id_var.get() or (current_ai_job_id if queue == "ai" else current_job_id)
    state = current_task_info_var.get()
    if not state:
        state = current_ai_task_info if queue == "ai" else current_task_info
    state["progress_current"] = current
    state["progress_total"] = total
    if label:
        state["progress_label"] = label
    if not job_id:
        return
    await directus.update_job(job_id, {
        "progress_current": current,
        "progress_total": total,
        "progress_label": (label or "")[:512] if label else None,
    })


async def update_current_job_phase(queue: str, phase: str, label: Optional[str] = None, extra: Optional[dict] = None):
    job_id = current_job_id_var.get() or (current_ai_job_id if queue == "ai" else current_job_id)
    state = current_task_info_var.get()
    if not state:
        state = current_ai_task_info if queue == "ai" else current_task_info
    state["phase"] = phase
    if label:
        state["progress_label"] = label
    if extra:
        state.update(extra)
    if not job_id:
        return
    payload = {}
    if label:
        payload["progress_label"] = label[:512]
    if payload:
        await directus.update_job(job_id, payload)


async def job_status_counts(queue: str) -> dict:
    statuses = ["queued", "running", "paused", "error"]
    counts = {}
    for status in statuses:
        counts[status] = await directus.count_jobs(queue, status)
    counts["active"] = counts["queued"] + counts["running"] + counts["paused"]
    return counts


async def reset_stale_running_jobs_if_due(force: bool = False) -> int:
    global last_stale_job_reset
    now = time.monotonic()
    if not force and now - last_stale_job_reset < 60:
        return 0
    last_stale_job_reset = now
    stale = await reset_stale_running_jobs()
    if stale:
        logger.info(f"Re-queued {stale} stale running jobs")
    return stale


async def retry_or_fail_job(job: dict, error: Exception, stopped: bool = False):
    attempts = int(job.get("attempts") or 0) + 1
    max_attempts = max(1, int(job.get("max_attempts") or 3))
    error_message = STOPPED_BY_USER if stopped else (str(error) or repr(error))[:1000]
    now = now_iso()
    duration_seconds = job_duration_seconds(job)
    if stopped or attempts >= max_attempts:
        await directus.update_job(job["id"], {
            "status": "cancelled" if stopped else "error",
            "attempts": attempts,
            "finished_at": now,
            "duration_seconds": duration_seconds,
            "error_message": error_message,
            "last_error": error_message,
            "locked_at": None,
            "locked_by": None,
        })
        return
    await directus.update_job(job["id"], {
        "status": "queued",
        "attempts": attempts,
        "finished_at": now,
        "error_message": f"Retry {attempts}/{max_attempts}: {error_message}",
        "last_error": error_message,
        "progress_label": "retry queued",
        "locked_at": None,
        "locked_by": None,
    })
    logger.warning(f"Retrying job {job['id']} ({attempts}/{max_attempts}) after error: {error_message}")


async def update_video_ai_status(video_id: str, status: str, error: Optional[str] = None):
    await directus.update_video(video_id, {"ai_notes_status": status, "ai_notes_error": error})


async def heartbeat_job(job_id: str):
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            await directus.update_job(job_id, {"locked_at": now_iso()})
        except Exception as e:
            logger.warning(f"Could not heartbeat job {job_id}: {e}")


def normalize_claimed_job(row) -> Optional[dict]:
    if not row:
        return None
    job = dict(row)
    job["id"] = str(job["id"])
    payload = job.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    job["payload"] = payload or {}
    for key in ("created_at", "started_at", "finished_at", "locked_at"):
        if job.get(key) is not None:
            job[key] = job[key].isoformat()
    return job


def parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def job_duration_seconds(job: dict, end: Optional[datetime] = None) -> Optional[int]:
    started = parse_datetime(job.get("started_at"))
    if not started:
        return None
    finished = end or parse_datetime(job.get("finished_at")) or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return max(0, int((finished - started).total_seconds()))


def summarize_ai_metrics(metrics: Optional[dict]) -> str:
    if not metrics:
        return "AI metrics unavailable"
    parts = []
    if metrics.get("total_seconds") is not None:
        parts.append(f"total {metrics['total_seconds']}s")
    if metrics.get("first_token_seconds") is not None:
        parts.append(f"first token {metrics['first_token_seconds']}s")
    if metrics.get("prompt_eval_seconds") is not None:
        parts.append(f"prompt {metrics['prompt_eval_seconds']}s")
    if metrics.get("eval_seconds") is not None:
        token_rate = metrics.get("eval_tokens_per_second")
        suffix = f" ({token_rate} tok/s)" if token_rate else ""
        parts.append(f"generate {metrics['eval_seconds']}s{suffix}")
    if metrics.get("ollama_load_seconds") is not None:
        parts.append(f"load {metrics['ollama_load_seconds']}s")
    return " · ".join(parts) if parts else "AI metrics unavailable"


async def claim_next_job(queue: str, worker_name: str) -> Optional[dict]:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH next_job AS (
                SELECT id
                FROM jobs
                WHERE queue = $1
                  AND status = 'queued'
                ORDER BY sort_order, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE jobs
            SET
                status = 'running',
                started_at = NOW(),
                finished_at = NULL,
                error_message = NULL,
                progress_current = NULL,
                progress_total = NULL,
                progress_label = NULL,
                duration_seconds = NULL,
                metrics = NULL,
                locked_at = NOW(),
                locked_by = $2
            WHERE id = (SELECT id FROM next_job)
            RETURNING
                id, queue, type, label, status, sort_order, payload, dedupe_key,
                attempts, max_attempts, progress_current, progress_total, progress_label,
                locked_at, locked_by, created_at, started_at, finished_at,
                error_message, last_error, duration_seconds, metrics
            """,
            queue,
            worker_name,
        )
    return normalize_claimed_job(row)


async def reset_stale_running_jobs(max_age_minutes: int = STALE_JOB_MINUTES) -> int:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE jobs
            SET
                status = 'queued',
                error_message = 'Re-queued stale running job after worker heartbeat timeout',
                duration_seconds = NULL,
                metrics = NULL,
                locked_at = NULL,
                locked_by = NULL
            WHERE status = 'running'
              AND locked_at IS NOT NULL
              AND locked_at < NOW() - make_interval(mins => $1::int)
            """,
            max_age_minutes,
        )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def reset_owned_running_jobs(worker_id: str, queues: set[str]) -> int:
    """Re-queue jobs left behind by a previous instance of this worker service."""
    if not worker_id or not queues:
        return 0
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE jobs
            SET
                status = 'queued',
                error_message = 'Re-queued running job after worker restart',
                duration_seconds = NULL,
                metrics = NULL,
                locked_at = NULL,
                locked_by = NULL
            WHERE status = 'running'
              AND locked_by LIKE $1
              AND queue = ANY($2::text[])
            """,
            f"{worker_id}:%",
            sorted(queues),
        )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def ensure_database_indexes():
    statements = [
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_by VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS idx_videos_uploaded_at ON videos (uploaded_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos (channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_videos_members_only ON videos (is_members_only)",
        "CREATE INDEX IF NOT EXISTS idx_videos_ai_notes_status ON videos (ai_notes_status)",
        "CREATE INDEX IF NOT EXISTS idx_videos_summary_missing ON videos (id) WHERE summary IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_videos_thumbnail_missing ON videos (id) WHERE thumbnail_url IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue_status_sort ON jobs (queue, status, sort_order, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active ON jobs (queue, dedupe_key) WHERE status IN ('queued', 'running', 'paused') AND dedupe_key IS NOT NULL",
    ]
    try:
        conn = await asyncpg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )
    except Exception as e:
        logger.warning(f"Could not connect to Postgres for index bootstrap: {e}")
        return
    try:
        await conn.execute("SELECT pg_advisory_lock(hashtext('youtube_video_transcript:index_bootstrap'))")
        try:
            await conn.execute("""
                WITH ranked AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY queue, dedupe_key
                            ORDER BY
                                CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                                created_at
                        ) AS rn
                    FROM jobs
                    WHERE dedupe_key IS NOT NULL
                      AND status IN ('queued', 'running', 'paused')
                )
                UPDATE jobs
                SET
                    status = 'cancelled',
                    finished_at = NOW(),
                    error_message = 'Cancelled duplicate active job during dedupe cleanup'
                WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """)
        except Exception as e:
            logger.warning(f"Could not clean duplicate active jobs before index bootstrap: {e}")
        for statement in statements:
            try:
                await conn.execute(statement)
            except Exception as e:
                logger.warning(f"Could not ensure index with statement '{statement}': {e}")
        logger.info("Ensured database indexes")
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock(hashtext('youtube_video_transcript:index_bootstrap'))")
        except Exception:
            pass
        await conn.close()


# ---- Worker ----

FETCH_HANDLERS: dict = {}  # populated after handler functions are defined
AI_HANDLERS: dict = {}


async def worker_loop(worker_name: str = "fetch-worker"):
    """Main background worker that processes queued tasks."""
    global stop_flag, current_task_info, current_job_id
    while True:
        if stop_flag:
            await asyncio.sleep(WORKER_IDLE_SLEEP)
            continue
        try:
            await reset_stale_running_jobs_if_due()
        except Exception as e:
            logger.warning(f"Could not reset stale fetch jobs: {e}")
        try:
            job = await claim_next_job("fetch", worker_name)
        except Exception as e:
            logger.warning(f"Could not poll fetch jobs: {e}")
            await asyncio.sleep(WORKER_POLL_BACKOFF)
            continue

        if not job:
            await asyncio.sleep(WORKER_IDLE_SLEEP)
            continue

        await refresh_app_settings_if_due(force=True)
        task = job.get("payload") or {}
        task_type = task.get("type")
        current_job_id = job["id"]
        current_task_info = {}
        job_id_token = current_job_id_var.set(job["id"])
        job_queue_token = current_job_queue_var.set("fetch")
        task_info_token = current_task_info_var.set(current_task_info)
        heartbeat_task = asyncio.create_task(heartbeat_job(job["id"]))
        try:
            handler = FETCH_HANDLERS.get(task_type)
            if not handler:
                raise ValueError(f"Unknown fetch job type: {task_type}")
            await handler(task)
            latest = await directus.get_job(job["id"])
            if latest and latest.get("status") != "cancelled":
                finished = datetime.now(timezone.utc)
                await directus.update_job(job["id"], {
                    "status": "done",
                    "finished_at": finished.isoformat(),
                    "duration_seconds": job_duration_seconds(job, finished),
                    "locked_at": None,
                    "locked_by": None,
                })
        except asyncio.CancelledError:
            await retry_or_fail_job(job, RuntimeError(STOPPED_BY_USER), stopped=True)
            raise
        except Exception as e:
            logger.error(f"Worker error on task {task}: {e}", exc_info=True)
            await retry_or_fail_job(job, e)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            current_job_id_var.reset(job_id_token)
            current_job_queue_var.reset(job_queue_token)
            current_task_info_var.reset(task_info_token)
            current_task_info = {}
            current_job_id = None


async def ai_worker_loop(worker_name: str = "ai-worker"):
    """Background worker for AI notes so LLM calls do not block fetching."""
    global stop_flag, current_ai_task_info, current_ai_job_id
    while True:
        if stop_flag:
            await asyncio.sleep(WORKER_IDLE_SLEEP)
            continue
        await refresh_app_settings_if_due()
        if not AI_NOTES_WORKER_ENABLED:
            await asyncio.sleep(WORKER_POLL_BACKOFF)
            continue
        try:
            await reset_stale_running_jobs_if_due()
        except Exception as e:
            logger.warning(f"Could not reset stale AI jobs: {e}")
        try:
            job = await claim_next_job("ai", worker_name)
        except Exception as e:
            logger.warning(f"Could not poll AI jobs: {e}")
            await asyncio.sleep(WORKER_POLL_BACKOFF)
            continue

        if not job:
            await refresh_app_settings_if_due()
            await maybe_enqueue_ai_year_backfill(source=worker_name)
            await asyncio.sleep(WORKER_IDLE_SLEEP)
            continue

        await refresh_app_settings_if_due(force=True)
        task = job.get("payload") or {}
        task_type = task.get("type")
        current_ai_job_id = job["id"]
        current_ai_task_info = {}
        job_id_token = current_job_id_var.set(job["id"])
        job_queue_token = current_job_queue_var.set("ai")
        task_info_token = current_task_info_var.set(current_ai_task_info)
        heartbeat_task = asyncio.create_task(heartbeat_job(job["id"]))
        try:
            handler = AI_HANDLERS.get(task_type)
            if not handler:
                raise ValueError(f"Unknown AI job type: {task_type}")
            await handler(task)
            latest = await directus.get_job(job["id"])
            if latest and latest.get("status") != "cancelled":
                finished = datetime.now(timezone.utc)
                await directus.update_job(job["id"], {
                    "status": "done",
                    "finished_at": finished.isoformat(),
                    "duration_seconds": job_duration_seconds(job, finished),
                    "locked_at": None,
                    "locked_by": None,
                })
        except asyncio.CancelledError:
            await retry_or_fail_job(job, RuntimeError(STOPPED_BY_USER), stopped=True)
            raise
        except Exception as e:
            logger.error(f"AI worker error on task {task}: {e}", exc_info=True)
            await retry_or_fail_job(job, e)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            current_job_id_var.reset(job_id_token)
            current_job_queue_var.reset(job_queue_token)
            current_task_info_var.reset(task_info_token)
            current_ai_task_info = {}
            current_ai_job_id = None
            if AI_NOTES_JOB_COOLDOWN_SECONDS > 0 and not stop_flag:
                await asyncio.sleep(AI_NOTES_JOB_COOLDOWN_SECONDS)


async def _backfill_metadata(existing: dict, videos: list):
    """Backfill lightweight metadata for already-stored videos from a fresh channel listing."""
    by_video_id = {v["video_id"]: v for v in videos}
    backfilled = 0
    for yt_id, stored_video in existing.items():
        channel_video = by_video_id.get(yt_id) or {}
        update_data = {}
        if not stored_video.get("uploaded_at") and channel_video.get("uploaded_at"):
            update_data["uploaded_at"] = channel_video["uploaded_at"]
        if not stored_video.get("thumbnail_url") and channel_video.get("thumbnail_url"):
            update_data["thumbnail_url"] = channel_video["thumbnail_url"]
        if channel_video and stored_video.get("is_members_only") != channel_video.get("is_members_only"):
            update_data["is_members_only"] = bool(channel_video.get("is_members_only"))
        if not update_data:
            continue
        try:
            await directus.update_video(stored_video["id"], update_data)
            backfilled += 1
        except Exception as e:
            logger.warning(f"Metadata backfill failed for {yt_id}: {e}")
    if backfilled:
        logger.info(f"Backfilled metadata for {backfilled} existing videos")


async def _process_channel_transcripts(
    transcript_videos: list,
    existing: dict,
    channel_url: str,
    channel_id: Optional[str],
    loop,
):
    """Fetch and store transcripts for new/incomplete channel videos. Errors per video are swallowed."""
    global current_task_info
    total = len(transcript_videos)
    for i, video in enumerate(transcript_videos):
        if stop_flag:
            break

        current_task_info = {
            "type": "channel",
            "url": channel_url,
            "phase": f"transcript {i+1}/{total}",
            "video": video.get("title", video["video_id"]),
        }
        await update_job_progress("fetch", i + 1, total, video.get("title") or video["video_id"])

        try:
            stored_video = existing.get(video["video_id"])
            directus_video_id = stored_video.get("id") if stored_video else None

            if not video.get("uploaded_at"):
                info = await loop.run_in_executor(None, fetch_video_info, video["video_id"])
                uploaded_at = parse_uploaded_at(info) if info else None
                if info:
                    video["is_members_only"] = is_members_only_video(info)
                if uploaded_at:
                    video["uploaded_at"] = uploaded_at
                    if not video.get("duration_seconds") and info.get("duration"):
                        video["duration_seconds"] = info.get("duration")
                    if not video.get("thumbnail_url"):
                        video["thumbnail_url"] = best_thumbnail_url(info)
                    logger.info(f"Filled upload date for {video['video_id']}: {uploaded_at}")

            if directus_video_id:
                metadata_update = {
                    field: video[field]
                    for field in ("title", "url", "duration_seconds", "uploaded_at", "thumbnail_url", "is_members_only")
                    if video.get(field) is not None
                }
                if metadata_update:
                    await directus.update_video(directus_video_id, metadata_update)
            else:
                created = await directus.create_video({**video, "channel_id": channel_id, "status": "pending"})
                directus_video_id = created.get("id")

            if i > 0:
                await rate_limited_sleep_transcript()

            transcript, transcript_timed = await loop.run_in_executor(
                None, fetch_transcript_variants, video["video_id"]
            )
            if directus_video_id:
                await directus.update_video(directus_video_id, {
                    "processed_at": now_iso(),
                    "status": "done" if transcript else "no_transcript",
                    "transcript": transcript or "",
                    "transcript_timed": transcript_timed or "",
                })
                if transcript and AI_NOTES_AUTO:
                    try:
                        await enqueue_ai_note(directus_video_id)
                    except Exception as e:
                        logger.warning(f"AI note enqueue failed for {video['video_id']}: {e}")

            logger.info(f"Video {video['video_id']}: {'done' if transcript else 'no_transcript'}")
        except Exception as e:
            logger.error(f"Transcript processing failed for {video['video_id']}: {e}", exc_info=True)
            if existing.get(video["video_id"]):
                try:
                    await directus.update_video(existing[video["video_id"]]["id"], {
                        "status": "error",
                        "processed_at": now_iso(),
                    })
                except Exception:
                    pass


async def process_channel_task(task: dict):
    """Process a channel: fetch video list + transcripts."""
    global current_task_info
    channel_url = task["channel_url"]
    channel_id = task.get("channel_id")

    current_task_info = {"type": "channel", "url": channel_url, "phase": "fetching video list"}
    if channel_id:
        await directus.update_channel(channel_id, {"status": "processing", "error_message": None})

    try:
        loop = asyncio.get_event_loop()
        videos = await loop.run_in_executor(None, fetch_channel_videos, channel_url)

        if not videos:
            if channel_id:
                await directus.update_channel(channel_id, {
                    "status": "error",
                    "error_message": "No videos found or channel not accessible",
                })
            return

        existing = {}
        if channel_id:
            existing_videos = await directus.get_videos_by_channel(channel_id)
            existing = {v["video_id"]: v for v in existing_videos}

        new_videos = [v for v in videos if v["video_id"] not in existing]
        transcript_videos = [
            v for v in videos
            if v["video_id"] not in existing
            or (existing.get(v["video_id"], {}).get("status") or "pending") != "done"
        ]
        logger.info(
            f"Channel {channel_url}: {len(videos)} total, {len(new_videos)} new, "
            f"{len(transcript_videos) - len(new_videos)} transcript retries"
        )

        if channel_id:
            await directus.update_channel(channel_id, {"video_count": len(videos)})

        if existing:
            await _backfill_metadata(existing, videos)

        await _process_channel_transcripts(transcript_videos, existing, channel_url, channel_id, loop)

        if channel_id:
            await directus.update_channel(channel_id, {
                "status": "done",
                "last_refreshed": now_iso(),
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
        "thumbnail_url": best_thumbnail_url(info) or (existing or {}).get("thumbnail_url"),
        "is_members_only": is_members_only_video(info) if info else bool((existing or {}).get("is_members_only")),
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
        "processed_at": now_iso(),
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
        await update_job_progress("fetch", i + 1, total, yt_id)

        info = await loop.run_in_executor(None, fetch_video_date_info, yt_id)
        if not info:
            logger.warning(f"No metadata available for {yt_id} (members-only/private/deleted/geo-blocked)")
            metadata_missing += 1
            continue

        uploaded_at = parse_uploaded_at(info)
        update_data = {"is_members_only": is_members_only_video(info)}

        if uploaded_at:
            update_data["uploaded_at"] = uploaded_at
            await directus.update_video(video["id"], update_data)
            logger.info(f"Updated date for {yt_id}: {uploaded_at}")
            updated += 1
        else:
            await directus.update_video(video["id"], update_data)
            logger.warning(f"Metadata fetched but no parseable date for {yt_id}")
            date_missing += 1

    checked = updated + metadata_missing + date_missing
    logger.info(
        f"Date refresh complete: checked={checked} updated={updated} "
        f"metadata_missing={metadata_missing} date_missing={date_missing}"
    )


async def process_refresh_thumbnails_task():
    """Fetch thumbnails for videos that are missing thumbnail_url."""
    global current_task_info
    videos = await directus.get_videos_missing_thumbnail()
    if not videos:
        logger.info("No videos with missing thumbnails")
        return

    total = len(videos)
    logger.info(f"Refreshing thumbnails for {total} videos")
    updated = 0
    missing = 0

    for i, video in enumerate(videos):
        if stop_flag:
            break

        yt_id = video["video_id"]
        current_task_info = {"type": "refresh_thumbnails", "phase": f"{i+1}/{total}", "video": yt_id}
        await update_job_progress("fetch", i + 1, total, yt_id)
        thumbnail_url = youtube_thumbnail_url(yt_id)
        if not thumbnail_url:
            missing += 1
            continue

        await directus.update_video(video["id"], {"thumbnail_url": thumbnail_url})
        updated += 1

    logger.info(f"Thumbnail refresh complete: checked={updated + missing} updated={updated} missing={missing}")


async def generate_and_store_ai_notes(directus_video_id: str, video: dict, fields: Optional[list[str]] = None) -> bool:
    """Generate and persist AI notebook fields for a single Directus video."""
    global current_ai_task_info
    requested_fields = [field for field in (fields or []) if field in AI_NOTE_GENERATED_FIELDS]
    current_ai_task_info = {
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
        if current_ai_job_id and metrics:
            await directus.update_job(current_ai_job_id, {
                "metrics": metrics,
                "progress_label": summarize_ai_metrics(metrics),
            })
            current_ai_task_info["metrics"] = metrics
            current_ai_task_info["progress_label"] = summarize_ai_metrics(metrics)
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
    global current_ai_task_info
    limit = max(1, min(int(task.get("limit") or AI_NOTES_BATCH_LIMIT), AI_NOTES_MAX_BATCH_LIMIT))
    videos = await directus.get_videos_missing_ai_notes(limit)
    active_video_ids = await directus.get_ai_note_job_video_ids()
    logger.info(f"Queueing AI note jobs for {len(videos)} candidate videos")

    queued = 0
    skipped = 0
    for i, video in enumerate(videos):
        if stop_flag:
            break
        video_id = video["id"]
        current_ai_task_info = {
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
    global current_ai_task_info
    video_id = task["video_id"]
    video = await directus.get_video(video_id)
    if not video:
        logger.warning(f"AI notes video not found: {video_id}")
        return
    if not (video.get("transcript") or video.get("transcript_timed")):
        await update_video_ai_status(video_id, "error", "No transcript available for AI notes")
        return

    current_ai_task_info = {
        "type": "ai_note_video",
        "phase": "generating",
        "video_id": video_id,
        "video": video.get("title") or video.get("video_id"),
        "started_at": now_iso(),
    }
    if current_ai_job_id:
        await directus.update_job(current_ai_job_id, {"progress_label": "AI generation started"})
    fields = task.get("fields")
    await generate_and_store_ai_notes(video_id, video, fields if isinstance(fields, list) else None)
    elapsed = job_duration_seconds({"started_at": current_ai_task_info.get("started_at")})
    current_ai_task_info["duration_seconds"] = elapsed
    if current_ai_job_id and elapsed is not None:
        await directus.update_job(current_ai_job_id, {
            "progress_label": f"AI generation finished in {elapsed}s",
        })


async def enqueue_ai_note(video_id: str):
    """Mark a video as queued for AI notes and enqueue it on the AI worker."""
    await update_video_ai_status(video_id, "pending")
    task = {"type": "ai_note_video", "video_id": video_id}
    return await directus.create_job("ai", task, dedupe_key=job_dedupe_key("ai", task))


def _init_handlers():
    FETCH_HANDLERS.update({
        "channel": process_channel_task,
        "video": process_single_video_task,
        "refresh": process_refresh_task,
        "refresh_dates": lambda task: process_refresh_dates_task(),
        "refresh_thumbnails": lambda task: process_refresh_thumbnails_task(),
    })
    AI_HANDLERS.update({
        "ai_notes": process_ai_notes_task,
        "ai_note_video": process_single_ai_note_task,
    })

_init_handlers()


async def enqueue_fetch_job(task: dict, label: Optional[str] = None):
    """Create a persistent fetch job."""
    return await directus.create_job("fetch", task, label=label, dedupe_key=job_dedupe_key("fetch", task))


async def enqueue_ai_job(task: dict, label: Optional[str] = None):
    """Create a persistent AI job."""
    return await directus.create_job("ai", task, label=label, dedupe_key=job_dedupe_key("ai", task))


async def maybe_enqueue_ai_year_backfill(source: str = "scheduler", force: bool = False) -> dict:
    """Keep the AI queue filled with missing notes for the configured upload year."""
    global last_ai_year_backfill_attempt
    if not AI_NOTES_AUTO or not AI_NOTES_YEAR_BACKFILL_ENABLED or stop_flag:
        return {"enabled": False, "queued": 0, "skipped": 0}

    now = time.monotonic()
    if not force and source != "scheduler" and now - last_ai_year_backfill_attempt < AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS:
        return {"throttled": True, "queued": 0, "skipped": 0}
    last_ai_year_backfill_attempt = now

    active_jobs = await directus.count_jobs("ai", "queued,running,paused")
    if not force and active_jobs >= AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE:
        return {
            "queued": 0,
            "skipped": 0,
            "active_jobs": active_jobs,
            "target_active": AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            "year": AI_NOTES_YEAR_BACKFILL_YEAR,
        }

    capacity = AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT if force else min(
        AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        max(0, AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE - active_jobs),
    )
    if capacity <= 0:
        return {"queued": 0, "skipped": 0, "active_jobs": active_jobs}

    missing_total = await directus.count_videos_missing_ai_notes(AI_NOTES_YEAR_BACKFILL_YEAR)
    if missing_total <= 0:
        logger.info(f"AI year backfill complete for {AI_NOTES_YEAR_BACKFILL_YEAR}")
        return {
            "queued": 0,
            "skipped": 0,
            "missing_total": 0,
            "year": AI_NOTES_YEAR_BACKFILL_YEAR,
        }

    active_video_ids = await directus.get_ai_note_job_video_ids()
    scan_limit = min(AI_NOTES_MAX_BATCH_LIMIT, max(capacity * 5, capacity + len(active_video_ids)))
    videos = await directus.get_videos_missing_ai_notes(scan_limit, year=AI_NOTES_YEAR_BACKFILL_YEAR)

    queued = 0
    skipped = 0
    for video in videos:
        if queued >= capacity or stop_flag:
            break
        video_id = video["id"]
        if video_id in active_video_ids:
            skipped += 1
            continue
        await update_video_ai_status(video_id, "pending")
        job = await enqueue_ai_job({
            "type": "ai_note_video",
            "video_id": video_id,
            "backfill_year": AI_NOTES_YEAR_BACKFILL_YEAR,
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
            AI_NOTES_YEAR_BACKFILL_YEAR,
        )
    return {
        "queued": queued,
        "skipped": skipped,
        "missing_total": missing_total,
        "active_jobs": active_jobs,
        "target_active": AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
        "year": AI_NOTES_YEAR_BACKFILL_YEAR,
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


async def cleanup_old_jobs():
    """Delete done/cancelled jobs older than JOB_CLEANUP_DAYS days."""
    count = await directus.delete_old_jobs(older_than_days=JOB_CLEANUP_DAYS)
    if count > 0:
        logger.info(f"Cleaned up {count} old jobs (>{JOB_CLEANUP_DAYS}d)")


async def bootstrap_runtime(cleanup_pending: bool = True):
    logger.info("Waiting for Directus...")
    for _ in range(40):
        if await directus.health_check():
            break
        await asyncio.sleep(BOOTSTRAP_CHECK_INTERVAL)
    else:
        logger.warning("Directus not responding, continuing anyway")

    try:
        await directus.ensure_schema()
        await ensure_database_indexes()
        stale = await reset_stale_running_jobs()
        if stale:
            logger.info(f"Re-queued {stale} stale running jobs")
        if cleanup_pending:
            await cleanup_orphan_ai_pending_videos()
    except Exception as e:
        logger.error(f"Schema bootstrap error: {e}", exc_info=True)
    await load_schedule_settings()
    await load_app_settings()


def create_worker_tasks() -> list[asyncio.Task]:
    tasks = []
    if "fetch" in WORKER_QUEUES:
        for index in range(FETCH_WORKER_CONCURRENCY):
            name = f"{WORKER_ID}:fetch:{index + 1}"
            tasks.append(asyncio.create_task(worker_loop(name), name=name))
    if "ai" in WORKER_QUEUES:
        for index in range(AI_WORKER_CONCURRENCY):
            name = f"{WORKER_ID}:ai:{index + 1}"
            tasks.append(asyncio.create_task(ai_worker_loop(name), name=name))
    return tasks


async def run_worker_service():
    await bootstrap_runtime(cleanup_pending=True)
    owned = await reset_owned_running_jobs(WORKER_ID, WORKER_QUEUES)
    if owned:
        logger.info(f"Re-queued {owned} jobs left by previous {WORKER_ID} instance")
    tasks = create_worker_tasks()
    if not tasks:
        logger.warning("Worker service started with no queues enabled")
        while True:
            await asyncio.sleep(IDLE_SLEEP)
    logger.info(f"Worker service started with {len(tasks)} worker task(s): {sorted(WORKER_QUEUES)}")
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_pg_pool()


# ---- App lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task, ai_worker_task, scheduler

    await bootstrap_runtime(cleanup_pending=FETCHER_ROLE in {"api", "all"})

    worker_tasks = []
    if FETCHER_ROLE in {"all", "worker"}:
        worker_tasks = create_worker_tasks()
        worker_task = next((task for task in worker_tasks if "fetch" in task.get_name()), None)
        ai_worker_task = next((task for task in worker_tasks if "ai" in task.get_name()), None)

    if FETCHER_ROLE in {"api", "all"}:
        start_refresh_scheduler()
    else:
        logger.info(f"Fetcher API started in role={FETCHER_ROLE}; scheduler disabled")

    yield

    # Cleanup
    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    if scheduler:
        scheduler.shutdown(wait=False)
    await close_pg_pool()
    await directus.close()


app = FastAPI(title="YouTube Transcript Fetcher", lifespan=lifespan)


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

class FetchChannelsRequest(BaseModel):
    urls: list[str]


class FetchVideoRequest(BaseModel):
    url: str
    channel_id: Optional[str] = None


class ScheduleRequest(BaseModel):
    cron: str
    timezone: str


class AppSettingsRequest(BaseModel):
    ollama_base_url: Optional[str] = None
    ollama_chat_model: Optional[str] = None
    ollama_timeout: Optional[int] = None
    ai_notes_max_chars: Optional[int] = None
    ai_notes_auto: Optional[bool] = None
    ai_notes_batch_limit: Optional[int] = None
    ai_notes_max_batch_limit: Optional[int] = None
    ai_notes_year_backfill_enabled: Optional[bool] = None
    ai_notes_year_backfill_year: Optional[int] = None
    ai_notes_year_backfill_batch_limit: Optional[int] = None
    ai_notes_year_backfill_target_active: Optional[int] = None
    ai_notes_year_backfill_interval_seconds: Optional[int] = None
    ai_notes_year_backfill_idle_seconds: Optional[int] = None
    ai_notes_worker_enabled: Optional[bool] = None
    ai_notes_job_cooldown_seconds: Optional[int] = None


class AiNotesRequest(BaseModel):
    limit: Optional[int] = None


class ChannelAiNotesRequest(BaseModel):
    limit: int = 500


class AiNoteRegenerateRequest(BaseModel):
    fields: list[str]


class JobMoveRequest(BaseModel):
    direction: str


UI_PAGE_SIZE = 100
UI_VIDEO_FIELDS = ",".join([
    "id,video_id,title,url,thumbnail_url,uploaded_at,duration_seconds,status,is_members_only,transcript,transcript_timed,whisper_status",
    "summary,topics,takeaways,questions,obsidian_note,study_guide,critique,ai_notes_status,ai_notes_generated_at,ai_notes_error",
    "channel_id.id,channel_id.name,channel_id.channel_handle",
])
UI_CHANNEL_UPDATE_FIELDS = {"name", "channel_url", "channel_handle", "status", "video_count", "error_message", "last_refreshed"}
UI_VIDEO_UPDATE_FIELDS = {
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
    local_tz = get_scheduler_timezone()
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
            "fetch_concurrency": FETCH_WORKER_CONCURRENCY,
            "ai_concurrency": AI_WORKER_CONCURRENCY,
        },
    }


@app.get("/status")
async def status():
    fetch_current = await current_job_snapshot("fetch", current_task_info, current_job_id)
    ai_current = await current_job_snapshot("ai", current_ai_task_info, current_ai_job_id)
    ollama_resources = await get_ollama_resource_status()
    fetch_counts = await job_status_counts("fetch")
    ai_counts = await job_status_counts("ai")
    ai_year_missing = None
    if AI_NOTES_AUTO and AI_NOTES_YEAR_BACKFILL_ENABLED:
        ai_year_missing = await directus.count_videos_missing_ai_notes(AI_NOTES_YEAR_BACKFILL_YEAR)
    return {
        "queue_size": fetch_counts["queued"],
        "ai_queue_size": ai_counts["queued"],
        "fetch_active_size": fetch_counts["active"],
        "ai_active_size": ai_counts["active"],
        "queues": {
            "fetch": fetch_counts,
            "ai": ai_counts,
        },
        "workers": {
            "fetch_concurrency": FETCH_WORKER_CONCURRENCY,
            "ai_concurrency": AI_WORKER_CONCURRENCY,
        },
        "stop_flag": stop_flag,
        "current_task": fetch_current,
        "current_ai_task": ai_current,
        "resources": {
            "ai_worker_enabled": AI_NOTES_WORKER_ENABLED,
            "ai_job_cooldown_seconds": AI_NOTES_JOB_COOLDOWN_SECONDS,
            "ai_worker_concurrency": AI_WORKER_CONCURRENCY,
            "ai_queue": ai_counts,
            "ollama": ollama_resources,
        },
        "schedule": {
            "cron": REFRESH_CRON,
            "timezone": SCHEDULER_TIMEZONE,
        },
        "ai_year_backfill": {
            "enabled": AI_NOTES_AUTO and AI_NOTES_YEAR_BACKFILL_ENABLED,
            "year": AI_NOTES_YEAR_BACKFILL_YEAR,
            "missing": ai_year_missing,
            "target_active": AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            "batch_limit": AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
            "interval_seconds": AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
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
            "fetch": current_job_id,
            "ai": current_ai_job_id,
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
                    "ai_worker_enabled": AI_NOTES_WORKER_ENABLED,
                    "ai_job_cooldown_seconds": AI_NOTES_JOB_COOLDOWN_SECONDS,
                    "ollama": {
                        "online": False,
                        "base_url": OLLAMA_BASE_URL,
                        "configured_model": OLLAMA_CHAT_MODEL,
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
    global worker_task, ai_worker_task
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


@app.get("/settings")
async def get_settings():
    return current_app_settings()


@app.patch("/settings")
async def update_settings(request: AppSettingsRequest):
    updates = request.model_dump(exclude_unset=True)
    next_settings = {**current_app_settings(), **updates}
    apply_app_settings(next_settings)
    gated_jobs = None
    if "ai_notes_worker_enabled" in updates:
        gated_jobs = await apply_ai_worker_queue_gate(AI_NOTES_WORKER_ENABLED)
    for key, value in current_app_settings().items():
        await directus.set_setting(key, str(value).lower() if isinstance(value, bool) else str(value))
    if FETCHER_ROLE in {"api", "all"}:
        start_refresh_scheduler()
    return {**current_app_settings(), "ai_worker_gated_jobs": gated_jobs}


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
    limit = max(1, min(request.limit, AI_NOTES_MAX_BATCH_LIMIT))
    job = await enqueue_ai_job({"type": "ai_notes", "limit": limit})
    return {"queued": True, "limit": limit, "job_id": job.get("id")}


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

    fields = [field for field in request.fields if field in AI_NOTE_GENERATED_FIELDS]
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
async def stop_processing(queue: Optional[str] = None):
    """Cancel jobs for a specific queue (fetch|ai) or both if queue is omitted."""
    global stop_flag, worker_task, ai_worker_task
    stop_fetch = queue in (None, "fetch")
    stop_ai = queue in (None, "ai")

    drained = await cancel_jobs("fetch", include_running=True) if stop_fetch else 0
    ai_drained = await cancel_jobs("ai", include_running=True) if stop_ai else 0

    return {
        "stopped": True,
        "queue": queue or "all",
        "drained": drained,
        "ai_drained": ai_drained,
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
