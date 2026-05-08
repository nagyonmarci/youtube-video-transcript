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


def parse_uploaded_at(info: dict) -> Optional[str]:
    """Return an ISO timestamp from the date fields yt-dlp may expose."""
    for field in ("upload_date", "release_date"):
        value = info.get(field)
        if isinstance(value, int):
            value = str(value)
        if isinstance(value, str) and len(value) == 8 and value.isdigit():
            try:
                return datetime(
                    int(value[:4]),
                    int(value[4:6]),
                    int(value[6:8]),
                    tzinfo=timezone.utc,
                ).isoformat()
            except ValueError:
                pass

    for field in ("timestamp", "release_timestamp"):
        value = info.get(field)
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
            except (OSError, OverflowError, ValueError):
                pass

    return None


def best_thumbnail_url(info: dict) -> Optional[str]:
    """Return the best available thumbnail URL from yt-dlp metadata."""
    thumbnail = info.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.strip():
        return thumbnail.strip()

    thumbnails = info.get("thumbnails")
    if not isinstance(thumbnails, list):
        return None

    candidates = []
    for item in thumbnails:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        width = item.get("width") or 0
        height = item.get("height") or 0
        preference = item.get("preference") or 0
        try:
            score = (int(width) * int(height), int(preference))
        except (TypeError, ValueError):
            score = (0, 0)
        candidates.append((score, url.strip()))

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def is_members_only_video(info: dict) -> bool:
    """Detect videos that are restricted to channel members/subscribers."""
    availability = str(info.get("availability") or "").lower()
    if availability in {"subscriber_only", "premium_only"}:
        return True

    badges = info.get("badges")
    if isinstance(badges, list):
        for badge in badges:
            if not isinstance(badge, dict):
                continue
            text = " ".join(
                str(badge.get(key) or "").lower()
                for key in ("label", "tooltip", "type")
            )
            if "member" in text or "subscriber" in text:
                return True

    return False


def youtube_thumbnail_url(video_id: str) -> Optional[str]:
    """Build a lightweight thumbnail URL from the YouTube video id."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id or ""):
        return None
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def fetch_video_info(video_url_or_id: str) -> dict:
    """Fetch full metadata for one video, using a low-bandwidth fallback format."""
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_url_or_id):
        video_url = f"https://www.youtube.com/watch?v={video_url_or_id}"
    else:
        video_url = video_url_or_id

    for fmt_args in [[], ["-f", "mhtml"]]:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-warnings",
            "--skip-download",
        ] + fmt_args + [video_url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.stdout.strip():
                return json.loads(result.stdout)
        except Exception as e:
            logger.debug(f"yt-dlp metadata fetch failed for {video_url}: {e}")
    return {}


def fetch_video_date_info(video_url_or_id: str) -> dict:
    """Fetch only date/duration/access metadata for one video."""
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_url_or_id):
        video_url = f"https://www.youtube.com/watch?v={video_url_or_id}"
    else:
        video_url = video_url_or_id

    cmd = [
        "yt-dlp",
        "--print",
        "%(upload_date|)s\t%(release_date|)s\t%(timestamp|)s\t%(release_timestamp|)s\t%(duration|)s\t%(availability|)s",
        "--no-warnings",
        "--skip-download",
        "--no-playlist",
        video_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        logger.debug(f"yt-dlp date metadata fetch failed for {video_url}: {e}")
        return {}

    if result.returncode != 0:
        error = (result.stderr or "").strip().splitlines()
        if error:
            logger.debug(f"yt-dlp date metadata unavailable for {video_url}: {error[-1]}")
        return {}

    line = (result.stdout or "").splitlines()
    if not line:
        return {}

    upload_date, release_date, timestamp, release_timestamp, duration, availability = (line[-1].split("\t") + [""] * 6)[:6]
    info = {
        "upload_date": upload_date or None,
        "release_date": release_date or None,
        "timestamp": timestamp or None,
        "release_timestamp": release_timestamp or None,
        "availability": availability or None,
    }
    if duration:
        try:
            info["duration"] = int(float(duration))
        except ValueError:
            pass
    return info


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

            duration = info.get("duration")
            duration_seconds = int(duration) if duration else None

            videos.append({
                "video_id": yt_id,
                "title": info.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={yt_id}",
                "duration_seconds": duration_seconds,
                "uploaded_at": parse_uploaded_at(info),
                "thumbnail_url": best_thumbnail_url(info),
                "is_members_only": is_members_only_video(info),
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


def format_transcript_timestamp(seconds: float) -> str:
    """Format transcript seconds as H:MM:SS or M:SS."""
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def transcript_entries_to_plain(entries: list[dict]) -> str:
    return " ".join(entry.get("text", "") for entry in entries).strip()


def transcript_entries_to_timed(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        text = entry.get("text", "").strip()
        if not text:
            continue
        start = entry.get("start", 0)
        try:
            timestamp = format_transcript_timestamp(float(start))
        except (TypeError, ValueError):
            timestamp = "0:00"
        lines.append(f"[{timestamp}] {text}")
    return "\n".join(lines).strip()


def fetch_transcript_variants(video_id: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch transcript and return (plain_text, timestamped_text).
    The timestamped text is best-effort and may be None for some fallbacks.
    """
    # Primary: youtube-transcript-api
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=["hu", "en", "a.hu", "a.en"],
        )
        plain = transcript_entries_to_plain(transcript_list)
        timed = transcript_entries_to_timed(transcript_list)
        return plain or None, timed or None
    except NoTranscriptFound:
        pass
    except TranscriptsDisabled:
        return None, None
    except Exception as e:
        logger.warning(f"youtube-transcript-api failed for {video_id}: {e}")

    # Fallback: try any available language
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        plain = transcript_entries_to_plain(transcript)
        timed = transcript_entries_to_timed(transcript)
        return plain or None, timed or None
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
                            vtt = f.read()
                        return _parse_vtt(vtt), _parse_vtt_with_timestamps(vtt)
    except Exception as e:
        logger.warning(f"yt-dlp subtitle fallback failed for {video_id}: {e}")

    return None, None


def fetch_transcript(video_id: str) -> Optional[str]:
    """
    Try to fetch transcript using youtube-transcript-api.
    Falls back to yt-dlp auto-subtitles.
    Returns plain text or None.
    """
    plain, _timed = fetch_transcript_variants(video_id)
    return plain


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


def _parse_vtt_with_timestamps(vtt_content: str) -> Optional[str]:
    """Parse WebVTT content into timestamped plain-text lines."""
    lines = vtt_content.splitlines()
    timed_lines = []
    current_timestamp = None
    prev_text = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.isdigit():
            continue
        if "-->" in line:
            start = line.split("-->", 1)[0].strip()
            current_timestamp = _format_vtt_timestamp(start)
            continue

        clean = re.sub(r'<[^>]+>', '', line).strip()
        if clean and clean != prev_text:
            prefix = f"[{current_timestamp}] " if current_timestamp else ""
            timed_lines.append(f"{prefix}{clean}")
            prev_text = clean

    return "\n".join(timed_lines).strip() or None


def _format_vtt_timestamp(value: str) -> str:
    value = value.replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(float(parts[2]))
        elif len(parts) == 2:
            hours = 0
            minutes = int(parts[0])
            seconds = int(float(parts[1]))
        else:
            return "0:00"
    except ValueError:
        return "0:00"

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


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
