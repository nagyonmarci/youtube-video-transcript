"""Job state utilities: claim, progress, heartbeat, retry, deduplication."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import config
import worker_state
from constants import HEARTBEAT_INTERVAL, STOPPED_BY_USER
from db import get_pg_pool
from directus_client import now_iso
from worker_state import directus

logger = logging.getLogger(__name__)


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
    job_id = worker_state.current_job_id_var.get() or (worker_state.current_ai_job_id if queue == "ai" else worker_state.current_job_id)
    state = worker_state.current_task_info_var.get()
    if not state:
        state = worker_state.current_ai_task_info if queue == "ai" else worker_state.current_task_info
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
    job_id = worker_state.current_job_id_var.get() or (worker_state.current_ai_job_id if queue == "ai" else worker_state.current_job_id)
    state = worker_state.current_task_info_var.get()
    if not state:
        state = worker_state.current_ai_task_info if queue == "ai" else worker_state.current_task_info
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
    now = time.monotonic()
    if not force and now - worker_state.last_stale_job_reset < 60:
        return 0
    worker_state.last_stale_job_reset = now
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
    job["payload"] = job.get("payload") or {}
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
            return datetime.fromisoformat(value)
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


async def reset_stale_running_jobs(max_age_minutes: int = config.STALE_JOB_MINUTES) -> int:
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
