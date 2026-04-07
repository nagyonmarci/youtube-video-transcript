"""YouTube channel and video transcript fetching with rate limiting."""

import asyncio
import logging
import random
import re
import subprocess
import json
from datetime import datetime, timezone
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

logger = logging.getLogger(__name__)

# Rate limiting: ~60 seconds between transcript requests (randomized ±15s)
TRANSCRIPT_DELAY_MIN = 45
TRANSCRIPT_DELAY_MAX = 75

# Delay between channel video-list fetches
CHANNEL_LIST_DELAY_MIN = 5
CHANNEL_LIST_DELAY_MAX = 15


def parse_channel_input(raw: str) -> str:
    """Normalize various YouTube channel URL formats to a yt-dlp compatible URL."""
    raw = raw.strip()
    if not raw:
        return ""

    # Already a full URL
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    # @handle shorthand
    if raw.startswith("@"):
        return f"https://www.youtube.com/{raw}/videos"

    # UCxxxx channel ID
    if raw.startswith("UC") and len(raw) > 20:
        return f"https://www.youtube.com/channel/{raw}/videos"

    # Bare handle without @
    return f"https://www.youtube.com/@{raw}/videos"


def normalize_to_videos_url(url: str) -> str:
    """Ensure the URL points to the /videos tab."""
    url = url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    return url


def extract_handle_from_url(url: str) -> str:
    """Extract a human-readable handle from a YouTube channel URL."""
    # @handle
    m = re.search(r'youtube\.com/@([^/?&]+)', url)
    if m:
        return f"@{m.group(1)}"
    # /channel/UCxxx
    m = re.search(r'youtube\.com/channel/([^/?&]+)', url)
    if m:
        return m.group(1)
    # /user/name
    m = re.search(r'youtube\.com/user/([^/?&]+)', url)
    if m:
        return m.group(1)
    return url


def fetch_channel_videos(channel_url: str) -> list[dict]:
    """
    Use yt-dlp to fetch video metadata for a channel.
    Returns list of dicts with: video_id, title, url, duration_seconds, uploaded_at
    """
    videos_url = normalize_to_videos_url(channel_url)
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        videos_url,
    ]
    logger.info(f"Fetching video list: {videos_url}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        logger.error("yt-dlp timed out fetching channel video list")
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        try:
            info = json.loads(line)
            yt_id = info.get("id", "")
            if not yt_id:
                continue

            # Parse upload date – try multiple fields yt-dlp may return
            uploaded_at = None
            upload_date = info.get("upload_date")
            if isinstance(upload_date, str) and len(upload_date) == 8:
                try:
                    uploaded_at = datetime(
                        int(upload_date[:4]),
                        int(upload_date[4:6]),
                        int(upload_date[6:8]),
                        tzinfo=timezone.utc,
                    ).isoformat()
                except ValueError:
                    pass
            if not uploaded_at:
                ts = info.get("timestamp") or info.get("release_timestamp")
                if isinstance(ts, (int, float)):
                    uploaded_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            duration = info.get("duration")
            duration_seconds = int(duration) if duration else None

            videos.append({
                "video_id": yt_id,
                "title": info.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={yt_id}",
                "duration_seconds": duration_seconds,
                "uploaded_at": uploaded_at,
            })
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    logger.info(f"Found {len(videos)} videos in channel")
    return videos


def fetch_channel_name(channel_url: str) -> str:
    """Fetch the channel display name via yt-dlp."""
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--playlist-end", "1",
        normalize_to_videos_url(channel_url),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.stdout:
            info = json.loads(result.stdout)
            return info.get("channel") or info.get("uploader") or info.get("title") or ""
    except Exception:
        pass
    return ""


def fetch_transcript(video_id: str) -> Optional[str]:
    """
    Try to fetch transcript using youtube-transcript-api.
    Falls back to yt-dlp auto-subtitles.
    Returns plain text or None.
    """
    # Primary: youtube-transcript-api
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=["hu", "en", "a.hu", "a.en"],
        )
        text = " ".join(entry["text"] for entry in transcript_list)
        return text.strip()
    except NoTranscriptFound:
        pass
    except TranscriptsDisabled:
        return None
    except Exception as e:
        logger.warning(f"youtube-transcript-api failed for {video_id}: {e}")

    # Fallback: try any available language
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join(entry["text"] for entry in transcript)
        return text.strip()
    except Exception:
        pass

    # Fallback: yt-dlp auto-subtitles
    try:
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            # Use -f mhtml as fallback format so yt-dlp can access metadata/subs
            # even when regular video formats are unavailable (bot-detected env)
            for fmt_args in [[], ["-f", "mhtml"]]:
                cmd = [
                    "yt-dlp",
                    "--write-auto-sub",
                    "--sub-format", "vtt",
                    "--skip-download",
                    "--no-warnings",
                ] + fmt_args + ["-o", f"{tmpdir}/%(id)s", video_url]
                subprocess.run(cmd, capture_output=True, timeout=60)
                for fname in os.listdir(tmpdir):
                    if fname.endswith(".vtt"):
                        with open(os.path.join(tmpdir, fname), "r", encoding="utf-8") as f:
                            return _parse_vtt(f.read())
    except Exception as e:
        logger.warning(f"yt-dlp subtitle fallback failed for {video_id}: {e}")

    return None


def _parse_vtt(vtt_content: str) -> str:
    """Parse WebVTT content into plain text."""
    lines = vtt_content.splitlines()
    texts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or "-->" in line or line.isdigit():
            continue
        # Strip HTML tags
        clean = re.sub(r'<[^>]+>', '', line)
        if clean:
            texts.append(clean)
    # Deduplicate consecutive identical lines
    deduped = []
    prev = None
    for t in texts:
        if t != prev:
            deduped.append(t)
            prev = t
    return " ".join(deduped).strip()


async def rate_limited_sleep_transcript():
    """Sleep a random duration between transcript fetches (~60s ±15s)."""
    delay = random.uniform(TRANSCRIPT_DELAY_MIN, TRANSCRIPT_DELAY_MAX)
    logger.info(f"Rate limiting: sleeping {delay:.1f}s before next transcript fetch")
    await asyncio.sleep(delay)


async def rate_limited_sleep_channel():
    """Sleep between channel video-list fetches (5-15s)."""
    delay = random.uniform(CHANNEL_LIST_DELAY_MIN, CHANNEL_LIST_DELAY_MAX)
    logger.info(f"Rate limiting: sleeping {delay:.1f}s before next channel fetch")
    await asyncio.sleep(delay)
