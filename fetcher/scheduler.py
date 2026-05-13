"""APScheduler setup and daily refresh job."""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import worker_state
from job_ops import cleanup_old_jobs, enqueue_fetch_job, maybe_enqueue_ai_year_backfill
from worker_state import directus
from youtube_fetcher import rate_limited_sleep_channel

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None

# Saved before night window starts so stop can restore them
_day_snapshot: dict = {}


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


async def ai_night_window_start():
    """Enable full-speed AI processing for the night window."""
    global _day_snapshot
    keys = ["ai_notes_auto", "ai_notes_job_cooldown_seconds", "ai_notes_year_backfill_enabled"]
    _day_snapshot = {}
    for key in keys:
        val = await directus.get_setting(key)
        if val is not None:
            _day_snapshot[key] = val
    await directus.set_setting("ai_notes_auto", "true")
    await directus.set_setting("ai_notes_job_cooldown_seconds", "0")
    await directus.set_setting("ai_notes_year_backfill_enabled", "true")
    await worker_state.load_app_settings()
    logger.info(
        "Night window started (hour=%s): auto=on, cooldown=0, backfill=on",
        config.AI_NIGHT_WINDOW_START_HOUR,
    )


async def ai_night_window_stop():
    """Restore day settings after the night window."""
    restore = _day_snapshot or {
        "ai_notes_auto": "false",
        "ai_notes_year_backfill_enabled": "false",
    }
    for key, value in restore.items():
        await directus.set_setting(key, value)
    await worker_state.load_app_settings()
    logger.info(
        "Night window ended (hour=%s): day settings restored",
        config.AI_NIGHT_WINDOW_STOP_HOUR,
    )


def start_refresh_scheduler():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)

    cron_parts = config.validate_schedule(config.REFRESH_CRON, config.SCHEDULER_TIMEZONE)
    minute, hour, day, month, day_of_week = cron_parts
    scheduler = AsyncIOScheduler(timezone=config.get_scheduler_timezone())
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
    # Backfill job always runs; maybe_enqueue_ai_year_backfill guards with config flags at runtime
    scheduler.add_job(
        maybe_enqueue_ai_year_backfill,
        "interval",
        seconds=config.AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
        id="ai_year_backfill",
        kwargs={"source": "scheduler"},
        next_run_time=datetime.now(config.get_scheduler_timezone()),
        replace_existing=True,
    )
    if config.AI_NIGHT_WINDOW_ENABLED:
        scheduler.add_job(
            ai_night_window_start,
            "cron",
            id="ai_night_window_start",
            replace_existing=True,
            hour=config.AI_NIGHT_WINDOW_START_HOUR,
            minute=0,
        )
        scheduler.add_job(
            ai_night_window_stop,
            "cron",
            id="ai_night_window_stop",
            replace_existing=True,
            hour=config.AI_NIGHT_WINDOW_STOP_HOUR,
            minute=0,
        )
    scheduler.start()
    logger.info(f"Daily refresh scheduled: {config.REFRESH_CRON} ({config.SCHEDULER_TIMEZONE})")
    if config.AI_NIGHT_WINDOW_ENABLED:
        logger.info(
            "AI night window enabled: %02d:00 → %02d:00 (auto=on, cooldown=0, backfill=on)",
            config.AI_NIGHT_WINDOW_START_HOUR,
            config.AI_NIGHT_WINDOW_STOP_HOUR,
        )
    if config.AI_NOTES_AUTO and config.AI_NOTES_YEAR_BACKFILL_ENABLED:
        logger.info(
            "AI year backfill active: year=%s interval=%ss target_active=%s batch=%s",
            config.AI_NOTES_YEAR_BACKFILL_YEAR,
            config.AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
            config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            config.AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        )
