"""APScheduler setup and daily refresh job."""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import worker_state
from job_ops import cleanup_old_jobs, enqueue_fetch_job, maybe_enqueue_ai_year_backfill
from log_store import cleanup_old_logs
from worker_state import directus
from youtube_fetcher import rate_limited_sleep_channel

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None

_night_mode_active: bool = False
# Directus values saved before night window, restored at stop
_NIGHT_OVERRIDE_KEYS = [
    "ai_notes_auto",
    "ai_notes_job_cooldown_seconds",
    "ai_notes_year_backfill_enabled",
]
_NIGHT_SNAPSHOT_KEYS = {
    "ai_notes_auto": "ai_night_snapshot_auto",
    "ai_notes_job_cooldown_seconds": "ai_night_snapshot_cooldown",
    "ai_notes_year_backfill_enabled": "ai_night_snapshot_backfill",
}


def in_hour_window(start_h: int, stop_h: int, now_hour: int) -> bool:
    """Overnight-aware hour window check (e.g. 19-07: in window if hour >= 19 or hour < 7)."""
    if start_h > stop_h:
        return now_hour >= start_h or now_hour < stop_h
    return start_h <= now_hour < stop_h


async def daily_refresh():
    """Automatically refresh all channels once a day."""
    logger.info("Starting daily channel refresh")
    channels = await directus.get_all_channels()
    for channel in channels:
        status = channel.get("status")
        if status == "processing":
            continue
        if status == "backlog" and config.CHANNEL_BACKLOG_WINDOW_ENABLED:
            # Large channels still working through their backlog are left to the evening sweep.
            continue
        await enqueue_fetch_job({"type": "refresh", "channel_id": channel["id"]})
        await rate_limited_sleep_channel()
    logger.info(f"Queued {len(channels)} channels for daily refresh")


async def sweep_channel_backlog():
    """Enqueue refresh jobs for channels still working through a large video backlog."""
    channels = await directus.get_channels_by_status("backlog")
    for channel in channels:
        await enqueue_fetch_job({"type": "refresh", "channel_id": channel["id"]})
        await rate_limited_sleep_channel()
    if channels:
        logger.info(f"Queued {len(channels)} backlog channels for evening catch-up")


async def check_channel_backlog_window():
    """Runs every 5 minutes; sweeps backlog channels while inside the configured evening window."""
    if not config.CHANNEL_BACKLOG_WINDOW_ENABLED:
        return

    tz = config.get_scheduler_timezone()
    now_hour = datetime.now(tz).hour
    if in_hour_window(config.CHANNEL_BACKLOG_START_HOUR, config.CHANNEL_BACKLOG_STOP_HOUR, now_hour):
        await sweep_channel_backlog()


async def ai_night_window_start():
    global _night_mode_active
    # Save current values to Directus snapshot keys (skip if already saved = restart during night)
    snapshot_exists = await directus.get_setting(_NIGHT_SNAPSHOT_KEYS["ai_notes_auto"])
    if snapshot_exists is None:
        for src, snap in _NIGHT_SNAPSHOT_KEYS.items():
            val = await directus.get_setting(src)
            # If auto is already true we restarted mid-night; use conservative day defaults
            if src == "ai_notes_auto" and val and val.lower() in ("true", "1", "yes", "on"):
                await directus.set_setting(snap, "false")
            else:
                await directus.set_setting(snap, val or "false")
    await directus.set_setting("ai_notes_auto", "true")
    await directus.set_setting("ai_notes_job_cooldown_seconds", "0")
    await directus.set_setting("ai_notes_year_backfill_enabled", "true")
    await worker_state.load_app_settings()
    _night_mode_active = True
    logger.info(
        "Night window started (%02d:00–%02d:00): auto=on, cooldown=0, backfill=on",
        config.AI_NIGHT_WINDOW_START_HOUR,
        config.AI_NIGHT_WINDOW_STOP_HOUR,
    )


async def ai_night_window_stop():
    global _night_mode_active
    for src, snap in _NIGHT_SNAPSHOT_KEYS.items():
        val = await directus.get_setting(snap)
        await directus.set_setting(src, val or "false")
        await directus.set_setting(snap, "")
    await worker_state.load_app_settings()
    _night_mode_active = False
    logger.info(
        "Night window ended (%02d:00): day settings restored",
        config.AI_NIGHT_WINDOW_STOP_HOUR,
    )


async def check_night_window():
    """Runs every 5 minutes; activates/deactivates the night window based on current config."""
    if not config.AI_NIGHT_WINDOW_ENABLED:
        if _night_mode_active:
            await ai_night_window_stop()
        return

    tz = config.get_scheduler_timezone()
    now_hour = datetime.now(tz).hour
    in_window = in_hour_window(config.AI_NIGHT_WINDOW_START_HOUR, config.AI_NIGHT_WINDOW_STOP_HOUR, now_hour)

    if in_window and not _night_mode_active:
        await ai_night_window_start()
    elif not in_window and _night_mode_active:
        await ai_night_window_stop()


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
    scheduler.add_job(
        cleanup_old_logs,
        "interval",
        hours=24,
        id="cleanup_old_logs",
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
    scheduler.add_job(
        check_night_window,
        "interval",
        minutes=5,
        id="check_night_window",
        replace_existing=True,
        next_run_time=datetime.now(config.get_scheduler_timezone()),
    )
    scheduler.add_job(
        check_channel_backlog_window,
        "interval",
        minutes=5,
        id="check_channel_backlog_window",
        replace_existing=True,
        next_run_time=datetime.now(config.get_scheduler_timezone()),
    )
    scheduler.start()
    logger.info(f"Daily refresh scheduled: {config.REFRESH_CRON} ({config.SCHEDULER_TIMEZONE})")
    if config.AI_NOTES_AUTO and config.AI_NOTES_YEAR_BACKFILL_ENABLED:
        logger.info(
            "AI year backfill active: year=%s interval=%ss target_active=%s batch=%s",
            config.AI_NOTES_YEAR_BACKFILL_YEAR,
            config.AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
            config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            config.AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        )
    if config.CHANNEL_BACKLOG_WINDOW_ENABLED:
        logger.info(
            "Channel backlog window active: %02d:00-%02d:00, cap=%s videos/run",
            config.CHANNEL_BACKLOG_START_HOUR,
            config.CHANNEL_BACKLOG_STOP_HOUR,
            config.CHANNEL_JOB_VIDEO_CAP,
        )
