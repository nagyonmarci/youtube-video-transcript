"""Fetch queue task handlers: channel, video, refresh variants."""

import asyncio
import logging
import re
from typing import Optional

import config
import worker_state
from directus_client import now_iso
from job_ops import enqueue_ai_note
from job_utils import update_job_progress, update_video_ai_status
from worker_state import directus
from youtube_fetcher import (
    fetch_channel_videos, fetch_video_info, fetch_transcript_variants,
    fetch_video_date_info, parse_uploaded_at, is_members_only_video,
    best_thumbnail_url, extract_handle_from_url, youtube_thumbnail_url,
    rate_limited_sleep_transcript, rate_limited_sleep_channel,
)

logger = logging.getLogger(__name__)


def _is_members_video(video: dict, stored_video: Optional[dict] = None) -> bool:
    """Return True when a video is known or labelled as members-only."""
    if video.get("is_members_only") or (stored_video or {}).get("is_members_only"):
        return True

    title = str(video.get("title") or (stored_video or {}).get("title") or "")
    return bool(re.search(r"\bmembers?\b", title, re.IGNORECASE))


async def _backfill_metadata(existing: dict, videos: list, loop):
    """Backfill lightweight metadata for already-stored videos from a fresh channel listing."""
    by_video_id = {v["video_id"]: v for v in videos}
    backfilled = 0
    date_calls_made = 0
    for yt_id, stored_video in existing.items():
        channel_video = by_video_id.get(yt_id) or {}
        update_data = {}
        is_members = bool(stored_video.get("is_members_only")) or _is_members_video(channel_video, stored_video)

        uploaded_at = channel_video.get("uploaded_at")
        if not stored_video.get("uploaded_at") and not uploaded_at and is_members:
            # Members-only videos rarely get a precise date from the flat-playlist listing,
            # and never reach the transcript-processing path that would normally backfill this.
            if date_calls_made > 0:
                await rate_limited_sleep_channel()
            date_info = await loop.run_in_executor(None, fetch_video_date_info, yt_id)
            date_calls_made += 1
            if date_info:
                uploaded_at = parse_uploaded_at(date_info)
                if date_info.get("duration") and not stored_video.get("duration_seconds"):
                    update_data["duration_seconds"] = date_info["duration"]
                if is_members_only_video(date_info):
                    is_members = True

        if not stored_video.get("uploaded_at") and uploaded_at:
            update_data["uploaded_at"] = uploaded_at
        if not stored_video.get("thumbnail_url") and channel_video.get("thumbnail_url"):
            update_data["thumbnail_url"] = channel_video["thumbnail_url"]
        if is_members and not stored_video.get("is_members_only"):
            update_data["is_members_only"] = True
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
    total = len(transcript_videos)
    for i, video in enumerate(transcript_videos):
        if worker_state.stop_flag or worker_state.stop_fetch_flag:
            break

        worker_state.current_task_info = {
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
                    **({"for_whisper": True} if not transcript else {}),
                })
                if transcript and config.AI_NOTES_AUTO:
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
    channel_url = task["channel_url"]
    channel_id = task.get("channel_id")

    worker_state.current_task_info = {"type": "channel", "url": channel_url, "phase": "fetching video list"}
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
        transcript_candidates = [
            v for v in videos
            if v["video_id"] not in existing
            or (existing.get(v["video_id"], {}).get("status") or "pending") not in ("done", "no_transcript")
        ]
        transcript_videos_all = [
            v for v in transcript_candidates
            if not _is_members_video(v, existing.get(v["video_id"]))
        ]
        # Newest-first listing order means capping here also prioritizes recent videos for free.
        transcript_videos = transcript_videos_all[:config.CHANNEL_JOB_VIDEO_CAP]
        has_more_backlog = len(transcript_videos_all) > len(transcript_videos)
        skipped_members = len(transcript_candidates) - len(transcript_videos_all)
        transcript_new = sum(1 for v in transcript_videos if v["video_id"] not in existing)
        transcript_retries = len(transcript_videos) - transcript_new
        logger.info(
            f"Channel {channel_url}: {len(videos)} total, {len(new_videos)} new, "
            f"{transcript_new} transcript new, {transcript_retries} transcript retries, "
            f"{skipped_members} members-only skipped, "
            f"{len(transcript_videos_all) - len(transcript_videos)} deferred to backlog"
        )

        if channel_id:
            await directus.update_channel(channel_id, {"video_count": len(videos)})

        if existing:
            await _backfill_metadata(existing, videos, loop)

        await _process_channel_transcripts(transcript_videos, existing, channel_url, channel_id, loop)

        if channel_id:
            await directus.update_channel(channel_id, {
                "status": "backlog" if has_more_backlog else "done",
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
    video_url = task["video_url"]
    worker_state.current_task_info = {"type": "video", "url": video_url, "phase": "fetching"}

    m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
    if not m:
        logger.error(f"Cannot extract video ID from: {video_url}")
        return

    yt_id = m.group(1)

    existing = await directus.find_video_by_yt_id(yt_id)
    if existing and existing.get("transcript"):
        logger.info(f"Video {yt_id} already exists, skipping")
        return
    if existing:
        logger.info(f"Video {yt_id} already exists without transcript, retrying existing record")

    loop = asyncio.get_event_loop()

    info = await loop.run_in_executor(None, fetch_video_info, video_url)
    uploaded_at = parse_uploaded_at(info) if info else None

    channel_id = task.get("channel_id") or (existing or {}).get("channel_id")
    if not channel_id and info:
        yt_channel_url = info.get("uploader_url") or info.get("channel_url") or ""
        yt_channel_name = info.get("channel") or info.get("uploader") or ""
        yt_channel_yt_id = info.get("channel_id") or ""
        if yt_channel_url or yt_channel_yt_id:
            handle = extract_handle_from_url(yt_channel_url) if yt_channel_url else yt_channel_yt_id
            existing_ch = await directus.find_channel_by_handle(handle)
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

    transcript, transcript_timed = await loop.run_in_executor(None, fetch_transcript_variants, yt_id)

    update_data = {
        "processed_at": now_iso(),
        "status": "done" if transcript else "no_transcript",
        "transcript": transcript or "",
        "transcript_timed": transcript_timed or "",
    }
    if not transcript and not video_data["is_members_only"]:
        update_data["for_whisper"] = True
    if directus_video_id:
        await directus.update_video(directus_video_id, update_data)
        if transcript and config.AI_NOTES_AUTO:
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
        if worker_state.stop_flag or worker_state.stop_fetch_flag:
            break

        yt_id = video["video_id"]
        worker_state.current_task_info = {"type": "refresh_dates", "phase": f"{i+1}/{total}", "video": yt_id}
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
    videos = await directus.get_videos_missing_thumbnail()
    if not videos:
        logger.info("No videos with missing thumbnails")
        return

    total = len(videos)
    logger.info(f"Refreshing thumbnails for {total} videos")
    updated = 0
    missing = 0

    for i, video in enumerate(videos):
        if worker_state.stop_flag or worker_state.stop_fetch_flag:
            break

        yt_id = video["video_id"]
        worker_state.current_task_info = {"type": "refresh_thumbnails", "phase": f"{i+1}/{total}", "video": yt_id}
        await update_job_progress("fetch", i + 1, total, yt_id)
        thumbnail_url = youtube_thumbnail_url(yt_id)
        if not thumbnail_url:
            missing += 1
            continue

        await directus.update_video(video["id"], {"thumbnail_url": thumbnail_url})
        updated += 1

    logger.info(f"Thumbnail refresh complete: checked={updated + missing} updated={updated} missing={missing}")
