"""Fetch and refresh endpoints."""

import logging

from fastapi import APIRouter, HTTPException

import config
from api_models import FetchChannelsRequest, FetchVideoRequest
from job_ops import enqueue_fetch_job
from worker_state import directus
from youtube_fetcher import (
    parse_channel_input, extract_handle_from_url,
    fetch_video_info, best_thumbnail_url, youtube_thumbnail_url,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/fetch-channels")
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

        existing = await directus.find_channel_by_handle(handle)
        if existing:
            channel_id = existing["id"]
            await enqueue_fetch_job({"type": "refresh", "channel_id": channel_id})
            queued.append({"url": channel_url, "action": "refresh", "id": channel_id})
        else:
            channel_record = await directus.create_channel({
                "name": handle,
                "channel_url": channel_url,
                "channel_handle": handle,
                "status": "pending",
                "video_count": 0,
            })
            channel_id = channel_record.get("id")

            await enqueue_fetch_job({
                "type": "channel",
                "channel_url": channel_url,
                "channel_id": channel_id,
            })
            queued.append({"url": channel_url, "action": "fetch", "id": channel_id})

    return {"queued": queued, "count": len(queued)}


@router.post("/fetch-video")
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


@router.post("/refresh-channel/{channel_id}")
async def refresh_channel(channel_id: str):
    """Manually refresh a channel: fetch new videos and retry incomplete transcripts."""
    channel = await directus.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    await enqueue_fetch_job({"type": "refresh", "channel_id": channel_id})
    return {"queued": True, "channel_id": channel_id}


@router.post("/refresh-dates")
async def refresh_dates():
    """Queue a task to fetch missing upload dates for all videos."""
    existing = await directus.get_active_job_by_type("fetch", "refresh_dates")
    if existing:
        return {"queued": False, "existing": True, "job_id": existing["id"]}
    job = await enqueue_fetch_job({"type": "refresh_dates"})
    return {"queued": True, "job_id": job.get("id")}


@router.post("/refresh-thumbnails")
async def refresh_thumbnails():
    """Queue a task to fetch missing thumbnail URLs for all videos."""
    existing = await directus.get_active_job_by_type("fetch", "refresh_thumbnails")
    if existing:
        return {"queued": False, "existing": True, "job_id": existing["id"]}
    job = await enqueue_fetch_job({"type": "refresh_thumbnails"})
    return {"queued": True, "job_id": job.get("id")}


@router.post("/refresh-thumbnail/{video_id}")
async def refresh_single_thumbnail(video_id: str):
    """Immediately re-fetch one video's thumbnail, bypassing the batch job queue."""
    video = await directus.find_video_by_yt_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    thumbnail_url = None
    try:
        thumbnail_url = best_thumbnail_url(fetch_video_info(video_id))
    except Exception as e:
        logger.warning(f"fetch_video_info failed for {video_id}: {e}")
    if not thumbnail_url:
        thumbnail_url = youtube_thumbnail_url(video_id)

    if thumbnail_url:
        await directus.update_video(video["id"], {"thumbnail_url": thumbnail_url})
    return {"thumbnail_url": thumbnail_url}
