"""APScheduler setup and daily refresh job."""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from job_ops import cleanup_old_jobs, enqueue_fetch_job, maybe_enqueue_ai_year_backfill
from worker_state import directus
from youtube_fetcher import rate_limited_sleep_channel

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None


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
    if config.AI_NOTES_AUTO and config.AI_NOTES_YEAR_BACKFILL_ENABLED:
        scheduler.add_job(
            maybe_enqueue_ai_year_backfill,
            "interval",
            seconds=config.AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
            id="ai_year_backfill",
            kwargs={"source": "scheduler"},
            next_run_time=datetime.now(config.get_scheduler_timezone()),
            replace_existing=True,
        )
    scheduler.start()
    logger.info(f"Daily refresh scheduled: {config.REFRESH_CRON} ({config.SCHEDULER_TIMEZONE})")
    if config.AI_NOTES_AUTO and config.AI_NOTES_YEAR_BACKFILL_ENABLED:
        logger.info(
            "AI year backfill scheduled: year=%s interval=%ss target_active=%s batch=%s",
            config.AI_NOTES_YEAR_BACKFILL_YEAR,
            config.AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
            config.AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
            config.AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        )
