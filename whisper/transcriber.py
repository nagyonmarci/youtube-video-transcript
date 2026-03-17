"""Audio download, conversion, and Whisper.cpp transcription."""

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

# Max video duration to process (default: 6 hours)
MAX_DURATION_SECONDS = int(os.environ.get("MAX_DURATION_SECONDS", "21600"))
# Min free disk space in bytes (2 GB)
MIN_FREE_DISK_BYTES = 2 * 1024 * 1024 * 1024


def check_disk_space(path: str = "/tmp") -> bool:
    """Check if there's enough free disk space."""
    usage = shutil.disk_usage(path)
    if usage.free < MIN_FREE_DISK_BYTES:
        logger.warning(f"Low disk space: {usage.free / 1e9:.1f} GB free")
        return False
    return True


MEMBERS_ONLY_PHRASES = (
    "members-only",
    "join this channel",
    "members only",
)


def is_members_only_error(stderr: str) -> bool:
    """Return True if yt-dlp failed because the video is members-only."""
    lowered = stderr.lower()
    return any(phrase in lowered for phrase in MEMBERS_ONLY_PHRASES)


class MembersOnlyError(Exception):
    """Raised when a video is members-only and cannot be downloaded."""


def download_audio(video_id: str, output_dir: str) -> Optional[str]:
    """Download worst-quality audio from YouTube via yt-dlp."""
    output_template = os.path.join(output_dir, f"{video_id}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "worstaudio/bestaudio",
        "--no-warnings",
        "--no-playlist",
        "-o", output_template,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    logger.info(f"Downloading audio for {video_id}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            if is_members_only_error(result.stderr):
                logger.warning(f"Members-only video, skipping: {video_id}")
                raise MembersOnlyError(video_id)
            logger.error(f"yt-dlp failed for {video_id}: {result.stderr[:500]}")
            return None
    except subprocess.TimeoutExpired:
        logger.error(f"yt-dlp download timed out for {video_id}")
        return None

    # Find the downloaded file
    for fname in os.listdir(output_dir):
        if fname.startswith(video_id) and not fname.endswith(".wav"):
            return os.path.join(output_dir, fname)

    logger.error(f"No audio file found after download for {video_id}")
    return None


def convert_to_wav(input_path: str, output_path: str, duration_seconds: int = 0) -> bool:
    """Convert audio to 16kHz mono WAV (whisper.cpp requirement)."""
    timeout = max(120, int(duration_seconds * 0.5)) if duration_seconds else 300
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        "-y",
        output_path,
    ]
    logger.info(f"Converting to WAV: {os.path.basename(input_path)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"ffmpeg conversion failed: {result.stderr[:500]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg conversion timed out")
        return False


def run_whisper(
    wav_path: str,
    model_path: str,
    language: str = "auto",
    threads: int = 4,
    duration_seconds: int = 0,
) -> Optional[str]:
    """Run whisper.cpp on a WAV file and return the transcript text."""
    timeout = max(600, int(duration_seconds * 3)) if duration_seconds else 3600

    cmd = [
        "whisper-cli",
        "-m", model_path,
        "-f", wav_path,
        "-t", str(threads),
        "--no-timestamps",
        "-otxt",
    ]
    if language != "auto":
        cmd.extend(["-l", language])

    logger.info(f"Running whisper.cpp (threads={threads}, lang={language})")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"whisper-cli failed: {result.stderr[:500]}")
            return None
    except subprocess.TimeoutExpired:
        logger.error(f"whisper-cli timed out after {timeout}s")
        return None

    # whisper.cpp -otxt writes to {wav_path}.txt
    txt_path = wav_path + ".txt"
    if not os.path.exists(txt_path):
        logger.error(f"Whisper output file not found: {txt_path}")
        return None

    with open(txt_path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        logger.warning("Whisper produced empty output")
        return None

    return text


def transcribe_video(
    video_id: str,
    duration_seconds: int = 0,
    model_path: str = "/app/models/ggml-large-v3.bin",
    language: str = "auto",
    threads: int = 4,
) -> Optional[str]:
    """Full pipeline: download audio -> convert to WAV -> run whisper.cpp."""
    # Check duration limit
    if duration_seconds and duration_seconds > MAX_DURATION_SECONDS:
        logger.warning(
            f"Video {video_id} too long ({duration_seconds}s > {MAX_DURATION_SECONDS}s), skipping"
        )
        return None

    # Check disk space
    if not check_disk_space():
        logger.error("Insufficient disk space, skipping transcription")
        return None

    tmpdir = tempfile.mkdtemp(prefix="whisper_")
    try:
        # 1. Download audio
        audio_path = download_audio(video_id, tmpdir)
        if not audio_path:
            return None

        # 2. Convert to WAV
        wav_path = os.path.join(tmpdir, f"{video_id}.wav")
        if not convert_to_wav(audio_path, wav_path, duration_seconds):
            return None

        # Remove original audio to save disk space
        if audio_path != wav_path:
            os.remove(audio_path)

        # 3. Run whisper
        transcript = run_whisper(wav_path, model_path, language, threads, duration_seconds)
        return transcript

    finally:
        # Clean up temp directory
        shutil.rmtree(tmpdir, ignore_errors=True)
