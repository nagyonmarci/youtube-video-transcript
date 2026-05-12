"""Shared mutable worker state: DirectusClient instance, stop flags, task tracking, ContextVars."""

import logging
import time
from contextvars import ContextVar
from typing import Optional

import asyncio

import config
from directus_client import DirectusClient

logger = logging.getLogger(__name__)

# Directus client (initialized once, never reassigned)
directus = DirectusClient(config.DIRECTUS_URL, config.DIRECTUS_TOKEN)

# Worker asyncio.Task handles
worker_task: Optional[asyncio.Task] = None
quick_worker_task: Optional[asyncio.Task] = None
ai_worker_task: Optional[asyncio.Task] = None

# Stop/pause flags (written by API endpoints, read by worker loops)
stop_flag = False
stop_fetch_flag = False
stop_quick_flag = False
stop_ai_flag = False

# In-memory current job state (informational; updated by worker loops)
current_task_info: dict = {}
current_quick_task_info: dict = {}
current_ai_task_info: dict = {}
current_job_id: Optional[str] = None
current_quick_job_id: Optional[str] = None
current_ai_job_id: Optional[str] = None

# Per-coroutine context (isolates concurrent worker state)
current_job_id_var: ContextVar[Optional[str]] = ContextVar("current_job_id", default=None)
current_job_queue_var: ContextVar[Optional[str]] = ContextVar("current_job_queue", default=None)
current_task_info_var: ContextVar[dict] = ContextVar("current_task_info", default={})

# Debounce timestamps (monotonic seconds)
last_ai_year_backfill_attempt = 0.0
last_runtime_settings_load = 0.0
last_stale_job_reset = 0.0


# ---- Settings loader (needs directus) ----

async def load_schedule_settings():
    try:
        stored_cron = await directus.get_setting("refresh_cron")
        stored_timezone = await directus.get_setting("scheduler_timezone")
        if stored_cron:
            config.REFRESH_CRON = stored_cron
        if stored_timezone:
            config.SCHEDULER_TIMEZONE = stored_timezone
        config.validate_schedule(config.REFRESH_CRON, config.SCHEDULER_TIMEZONE)
    except Exception as e:
        logger.warning(f"Could not load stored schedule settings, using current values: {e}")


async def save_schedule_settings(cron: str, timezone_name: str):
    await directus.set_setting("refresh_cron", cron)
    await directus.set_setting("scheduler_timezone", timezone_name)


async def load_app_settings():
    global last_runtime_settings_load
    settings = config.current_app_settings()
    try:
        stored = {}
        for key in settings.keys():
            value = await directus.get_setting(key)
            if value is not None:
                stored[key] = value
        config.apply_app_settings({**settings, **stored})
        last_runtime_settings_load = time.monotonic()
    except Exception as e:
        logger.warning(f"Could not load app settings, using current values: {e}")


async def refresh_app_settings_if_due(max_age_seconds: int = 30, force: bool = False):
    if force or time.monotonic() - last_runtime_settings_load >= max_age_seconds:
        await load_app_settings()
