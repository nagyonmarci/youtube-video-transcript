"""Worker loops, handler registry, bootstrap, and service entrypoint."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import config
import worker_state
from ai_tasks import process_ai_notes_task, process_single_ai_note_task, process_quick_note_task
from constants import (
    QUEUE_QUICK, QUEUE_AI,
    JOB_QUICK_NOTE_VIDEO, JOB_AI_NOTE_VIDEO,
    WORKER_IDLE_SLEEP, WORKER_POLL_BACKOFF, IDLE_SLEEP,
    STOPPED_BY_USER, BOOTSTRAP_CHECK_INTERVAL,
)
from db import ensure_database_indexes, close_pg_pool
from log_store import install_log_handler
from fetch_tasks import (
    process_channel_task, process_single_video_task, process_refresh_task,
    process_refresh_dates_task, process_refresh_thumbnails_task,
)
from job_ops import maybe_enqueue_ai_year_backfill, cleanup_orphan_ai_pending_videos
from job_utils import (
    heartbeat_job, claim_next_job, retry_or_fail_job,
    reset_stale_running_jobs_if_due, reset_stale_running_jobs,
    reset_owned_running_jobs, job_duration_seconds,
)
from worker_state import directus

logger = logging.getLogger(__name__)

FETCH_HANDLERS: dict = {}
QUICK_HANDLERS: dict = {}
AI_HANDLERS: dict = {}


def _init_handlers():
    FETCH_HANDLERS.update({
        "channel": process_channel_task,
        "video": process_single_video_task,
        "refresh": process_refresh_task,
        "refresh_dates": lambda task: process_refresh_dates_task(),
        "refresh_thumbnails": lambda task: process_refresh_thumbnails_task(),
    })
    QUICK_HANDLERS.update({
        JOB_QUICK_NOTE_VIDEO: process_quick_note_task,
    })
    AI_HANDLERS.update({
        "ai_notes": process_ai_notes_task,
        JOB_AI_NOTE_VIDEO: process_single_ai_note_task,
    })


_init_handlers()


async def _ai_on_idle(worker_name: str) -> None:
    await worker_state.refresh_app_settings_if_due()
    await maybe_enqueue_ai_year_backfill(source=worker_name)


async def run_worker(
    queue: str,
    handlers: dict,
    worker_name: str,
    *,
    label: str,
    error_prefix: str,
    stop_flag_attr: str,
    job_id_attr: str,
    task_info_attr: str,
    enabled_check: Optional[Callable[[], bool]] = None,
    on_idle: Optional[Callable[[str], Awaitable[None]]] = None,
    cooldown_seconds: Optional[Callable[[], int]] = None,
    refresh_each_iteration: bool = False,
):
    """Shared claim/dispatch/finish loop body for the fetch/quick/ai queue workers."""
    while True:
        if worker_state.stop_flag or getattr(worker_state, stop_flag_attr):
            await asyncio.sleep(WORKER_IDLE_SLEEP)
            continue
        if refresh_each_iteration:
            await worker_state.refresh_app_settings_if_due()
        if enabled_check is not None and not enabled_check():
            await asyncio.sleep(WORKER_POLL_BACKOFF)
            continue
        try:
            await reset_stale_running_jobs_if_due()
        except Exception as e:
            logger.warning(f"Could not reset stale {label} jobs: {e}")
        try:
            job = await claim_next_job(queue, worker_name)
        except Exception as e:
            logger.warning(f"Could not poll {label} jobs: {e}")
            await asyncio.sleep(WORKER_POLL_BACKOFF)
            continue

        if not job:
            if on_idle is not None:
                await on_idle(worker_name)
            await asyncio.sleep(WORKER_IDLE_SLEEP)
            continue

        await worker_state.refresh_app_settings_if_due(force=True)
        task = job.get("payload") or {}
        task_type = task.get("type")
        setattr(worker_state, job_id_attr, job["id"])
        setattr(worker_state, task_info_attr, {})
        job_id_token = worker_state.current_job_id_var.set(job["id"])
        job_queue_token = worker_state.current_job_queue_var.set(queue)
        task_info_token = worker_state.current_task_info_var.set(getattr(worker_state, task_info_attr))
        heartbeat_task = asyncio.create_task(heartbeat_job(job["id"]))
        try:
            handler = handlers.get(task_type)
            if not handler:
                raise ValueError(f"Unknown {label} job type: {task_type}")
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
            logger.error(f"{error_prefix} error on task {task}: {e}", exc_info=True)
            await retry_or_fail_job(job, e)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            worker_state.current_job_id_var.reset(job_id_token)
            worker_state.current_job_queue_var.reset(job_queue_token)
            worker_state.current_task_info_var.reset(task_info_token)
            setattr(worker_state, task_info_attr, {})
            setattr(worker_state, job_id_attr, None)
            if cooldown_seconds is not None:
                secs = cooldown_seconds()
                if secs > 0 and not worker_state.stop_flag and not getattr(worker_state, stop_flag_attr):
                    await asyncio.sleep(secs)


async def worker_loop(worker_name: str = "fetch-worker"):
    """Main background worker that processes queued tasks."""
    await run_worker(
        "fetch", FETCH_HANDLERS, worker_name,
        label="fetch", error_prefix="Worker",
        stop_flag_attr="stop_fetch_flag",
        job_id_attr="current_job_id", task_info_attr="current_task_info",
    )


async def ai_worker_loop(worker_name: str = "ai-worker"):
    """Background worker for AI notes so LLM calls do not block fetching."""
    await run_worker(
        "ai", AI_HANDLERS, worker_name,
        label="AI", error_prefix="AI worker",
        stop_flag_attr="stop_ai_flag",
        job_id_attr="current_ai_job_id", task_info_attr="current_ai_task_info",
        enabled_check=lambda: config.AI_NOTES_WORKER_ENABLED,
        on_idle=_ai_on_idle,
        cooldown_seconds=lambda: config.AI_NOTES_JOB_COOLDOWN_SECONDS,
        refresh_each_iteration=True,
    )


async def quick_worker_loop(worker_name: str = "quick-worker"):
    """Background worker for quick summaries — runs before the full AI notes worker."""
    await run_worker(
        QUEUE_QUICK, QUICK_HANDLERS, worker_name,
        label="quick", error_prefix="Quick worker",
        stop_flag_attr="stop_quick_flag",
        job_id_attr="current_quick_job_id", task_info_attr="current_quick_task_info",
        refresh_each_iteration=True,
    )


async def restart_ai_worker():
    """Cancel and recreate the AI worker."""
    if worker_state.ai_worker_task and not worker_state.ai_worker_task.done():
        worker_state.ai_worker_task.cancel()
        try:
            await worker_state.ai_worker_task
        except asyncio.CancelledError:
            pass
    worker_state.ai_worker_task = asyncio.create_task(ai_worker_loop())


async def bootstrap_runtime(cleanup_pending: bool = True):
    install_log_handler()
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
    await worker_state.load_schedule_settings()
    await worker_state.load_app_settings()


def create_worker_tasks() -> list[asyncio.Task]:
    tasks = []
    if "fetch" in config.WORKER_QUEUES:
        for index in range(config.FETCH_WORKER_CONCURRENCY):
            name = f"{config.WORKER_ID}:fetch:{index + 1}"
            tasks.append(asyncio.create_task(worker_loop(name), name=name))
    if QUEUE_QUICK in config.WORKER_QUEUES:
        for index in range(config.QUICK_WORKER_CONCURRENCY):
            name = f"{config.WORKER_ID}:quick:{index + 1}"
            tasks.append(asyncio.create_task(quick_worker_loop(name), name=name))
    if "ai" in config.WORKER_QUEUES:
        for index in range(config.AI_WORKER_CONCURRENCY):
            name = f"{config.WORKER_ID}:ai:{index + 1}"
            tasks.append(asyncio.create_task(ai_worker_loop(name), name=name))
    return tasks


async def run_worker_service():
    await bootstrap_runtime(cleanup_pending=True)
    owned = await reset_owned_running_jobs(config.WORKER_ID, config.WORKER_QUEUES)
    if owned:
        logger.info(f"Re-queued {owned} jobs left by previous {config.WORKER_ID} instance")
    tasks = create_worker_tasks()
    if not tasks:
        logger.warning("Worker service started with no queues enabled")
        while True:
            await asyncio.sleep(IDLE_SLEEP)
    logger.info(f"Worker service started with {len(tasks)} worker task(s): {sorted(config.WORKER_QUEUES)}")
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_pg_pool()
