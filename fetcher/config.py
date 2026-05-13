"""Application configuration: environment variables, helpers, and runtime settings."""

import logging
import os
import socket
from datetime import timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_notes import configure_ai_notes

logger = logging.getLogger(__name__)


# ---- Pure helpers ----

def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def bool_setting(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def int_setting(value, default: int, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def get_scheduler_timezone():
    try:
        return ZoneInfo(SCHEDULER_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning(f"Unknown scheduler timezone '{SCHEDULER_TIMEZONE}', falling back to UTC")
        return timezone.utc


def validate_schedule(cron: str, timezone_name: str):
    cron_parts = cron.split()
    if len(cron_parts) != 5:
        raise ValueError("A cron kifejezésnek pontosan 5 mezőből kell állnia")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Ismeretlen időzóna: {timezone_name}") from exc
    return cron_parts


# ---- Environment variables ----

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055")
DIRECTUS_TOKEN = required_env("DIRECTUS_TOKEN")
APP_API_TOKEN = required_env("APP_API_TOKEN")
APP_CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("APP_CORS_ORIGINS", "http://yt.test,http://localhost:4321").split(",")
    if origin.strip()
]
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "directus")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "directus")
POSTGRES_PASSWORD = required_env("POSTGRES_PASSWORD")
REFRESH_CRON = os.environ.get("REFRESH_CRON", "0 7 * * *")
SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Europe/Budapest")
AI_NOTES_AUTO = os.environ.get("AI_NOTES_AUTO", "false").lower() in {"1", "true", "yes", "on"}
AI_NOTES_BATCH_LIMIT = int(os.environ.get("AI_NOTES_BATCH_LIMIT", "10"))
AI_NOTES_MAX_BATCH_LIMIT = int(os.environ.get("AI_NOTES_MAX_BATCH_LIMIT", "20000"))
AI_NOTES_YEAR_BACKFILL_ENABLED = os.environ.get("AI_NOTES_YEAR_BACKFILL_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
AI_NOTES_YEAR_BACKFILL_YEAR = int(os.environ.get("AI_NOTES_YEAR_BACKFILL_YEAR", "2026"))
AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT = max(1, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT", "50")))
AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE = max(1, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE", "100")))
AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS = max(30, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS", "300")))
AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS = max(10, int(os.environ.get("AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS", "60")))
AI_NOTES_WORKER_ENABLED = os.environ.get("AI_NOTES_WORKER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
AI_NOTES_JOB_COOLDOWN_SECONDS = max(0, int(os.environ.get("AI_NOTES_JOB_COOLDOWN_SECONDS", "0")))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:31b-mlx-bf16")
AI_NOTES_MAX_CHARS = int(os.environ.get("AI_NOTES_MAX_CHARS", "45000"))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))
AI_NOTES_QUICK_ENABLED = os.environ.get("AI_NOTES_QUICK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
OLLAMA_QUICK_MODEL = os.environ.get("OLLAMA_QUICK_MODEL", "qwen3:4b")
OLLAMA_QUICK_TIMEOUT = int(os.environ.get("OLLAMA_QUICK_TIMEOUT", "120"))
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
OLLAMA_QUICK_NUM_CTX = int(os.environ.get("OLLAMA_QUICK_NUM_CTX", "4096"))
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.1"))
OLLAMA_NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "8192"))
AI_PROVIDER = os.environ.get("AI_PROVIDER", "ollama")
AI_CLOUD_MODEL = os.environ.get("AI_CLOUD_MODEL", "claude-opus-4-7")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
FETCHER_ROLE = os.environ.get("FETCHER_ROLE", "all").lower()
WORKER_QUEUES = {item.strip() for item in os.environ.get("WORKER_QUEUES", "fetch,ai").split(",") if item.strip()}
FETCH_WORKER_CONCURRENCY = max(0, int(os.environ.get("FETCH_WORKER_CONCURRENCY", "1")))
QUICK_WORKER_CONCURRENCY = max(0, int(os.environ.get("QUICK_WORKER_CONCURRENCY", "1")))
AI_WORKER_CONCURRENCY = max(0, int(os.environ.get("AI_WORKER_CONCURRENCY", "1")))
STALE_JOB_MINUTES = max(5, int(os.environ.get("STALE_JOB_MINUTES", "30")))
JOB_CLEANUP_DAYS = int(os.environ.get("JOB_CLEANUP_DAYS", "7"))
WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"

AI_NOTE_GENERATED_FIELDS = {
    "summary",
    "topics",
    "takeaways",
    "questions",
    "obsidian_note",
    "study_guide",
    "critique",
}


# ---- Runtime settings snapshot + mutation ----

def current_app_settings() -> dict:
    return {
        "ollama_base_url": OLLAMA_BASE_URL,
        "ollama_chat_model": OLLAMA_CHAT_MODEL,
        "ollama_timeout": OLLAMA_TIMEOUT,
        "ai_notes_max_chars": AI_NOTES_MAX_CHARS,
        "ai_notes_auto": AI_NOTES_AUTO,
        "ai_notes_batch_limit": AI_NOTES_BATCH_LIMIT,
        "ai_notes_max_batch_limit": AI_NOTES_MAX_BATCH_LIMIT,
        "ai_notes_year_backfill_enabled": AI_NOTES_YEAR_BACKFILL_ENABLED,
        "ai_notes_year_backfill_year": AI_NOTES_YEAR_BACKFILL_YEAR,
        "ai_notes_year_backfill_batch_limit": AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT,
        "ai_notes_year_backfill_target_active": AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE,
        "ai_notes_year_backfill_interval_seconds": AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS,
        "ai_notes_year_backfill_idle_seconds": AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS,
        "ai_notes_worker_enabled": AI_NOTES_WORKER_ENABLED,
        "ai_notes_job_cooldown_seconds": AI_NOTES_JOB_COOLDOWN_SECONDS,
        "ai_notes_quick_enabled": AI_NOTES_QUICK_ENABLED,
        "ollama_quick_model": OLLAMA_QUICK_MODEL,
        "ollama_quick_timeout": OLLAMA_QUICK_TIMEOUT,
        "ollama_num_ctx": OLLAMA_NUM_CTX,
        "ollama_quick_num_ctx": OLLAMA_QUICK_NUM_CTX,
        "ollama_temperature": OLLAMA_TEMPERATURE,
        "ollama_num_predict": OLLAMA_NUM_PREDICT,
        "ai_provider": AI_PROVIDER,
        "ai_cloud_model": AI_CLOUD_MODEL,
        "anthropic_api_key": ANTHROPIC_API_KEY,
        "openai_api_key": OPENAI_API_KEY,
        "openai_base_url": OPENAI_BASE_URL,
    }


def apply_app_settings(settings: dict) -> None:
    global OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_TIMEOUT, AI_NOTES_MAX_CHARS
    global AI_NOTES_AUTO, AI_NOTES_BATCH_LIMIT, AI_NOTES_MAX_BATCH_LIMIT
    global AI_NOTES_YEAR_BACKFILL_ENABLED, AI_NOTES_YEAR_BACKFILL_YEAR
    global AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT, AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE
    global AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS, AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS
    global AI_NOTES_WORKER_ENABLED, AI_NOTES_JOB_COOLDOWN_SECONDS
    global AI_NOTES_QUICK_ENABLED, OLLAMA_QUICK_MODEL, OLLAMA_QUICK_TIMEOUT
    global OLLAMA_NUM_CTX, OLLAMA_QUICK_NUM_CTX, OLLAMA_TEMPERATURE, OLLAMA_NUM_PREDICT
    global AI_PROVIDER, AI_CLOUD_MODEL, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL

    OLLAMA_BASE_URL = str(settings.get("ollama_base_url") or OLLAMA_BASE_URL).strip().rstrip("/")
    OLLAMA_CHAT_MODEL = str(settings.get("ollama_chat_model") or OLLAMA_CHAT_MODEL).strip()
    OLLAMA_TIMEOUT = int_setting(settings.get("ollama_timeout"), OLLAMA_TIMEOUT, 30)
    AI_NOTES_MAX_CHARS = int_setting(settings.get("ai_notes_max_chars"), AI_NOTES_MAX_CHARS, 1000)
    AI_NOTES_AUTO = bool_setting(settings.get("ai_notes_auto", AI_NOTES_AUTO))
    AI_NOTES_BATCH_LIMIT = int_setting(settings.get("ai_notes_batch_limit"), AI_NOTES_BATCH_LIMIT, 1)
    AI_NOTES_MAX_BATCH_LIMIT = int_setting(settings.get("ai_notes_max_batch_limit"), AI_NOTES_MAX_BATCH_LIMIT, 1)
    AI_NOTES_YEAR_BACKFILL_ENABLED = bool_setting(settings.get("ai_notes_year_backfill_enabled", AI_NOTES_YEAR_BACKFILL_ENABLED))
    AI_NOTES_YEAR_BACKFILL_YEAR = int_setting(settings.get("ai_notes_year_backfill_year"), AI_NOTES_YEAR_BACKFILL_YEAR, 2005)
    AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT = int_setting(settings.get("ai_notes_year_backfill_batch_limit"), AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT, 1)
    AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE = int_setting(settings.get("ai_notes_year_backfill_target_active"), AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE, 1)
    AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS = int_setting(settings.get("ai_notes_year_backfill_interval_seconds"), AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS, 30)
    AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS = int_setting(settings.get("ai_notes_year_backfill_idle_seconds"), AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS, 10)
    AI_NOTES_WORKER_ENABLED = bool_setting(settings.get("ai_notes_worker_enabled", AI_NOTES_WORKER_ENABLED))
    AI_NOTES_JOB_COOLDOWN_SECONDS = int_setting(settings.get("ai_notes_job_cooldown_seconds"), AI_NOTES_JOB_COOLDOWN_SECONDS, 0, 3600)
    AI_NOTES_QUICK_ENABLED = bool_setting(settings.get("ai_notes_quick_enabled", AI_NOTES_QUICK_ENABLED))
    if settings.get("ollama_quick_model"):
        OLLAMA_QUICK_MODEL = str(settings["ollama_quick_model"]).strip()
    OLLAMA_QUICK_TIMEOUT = int_setting(settings.get("ollama_quick_timeout"), OLLAMA_QUICK_TIMEOUT, 10)
    OLLAMA_NUM_CTX = int_setting(settings.get("ollama_num_ctx"), OLLAMA_NUM_CTX, 2048)
    OLLAMA_QUICK_NUM_CTX = int_setting(settings.get("ollama_quick_num_ctx"), OLLAMA_QUICK_NUM_CTX, 512)
    if settings.get("ollama_temperature") is not None:
        OLLAMA_TEMPERATURE = float(settings.get("ollama_temperature") or OLLAMA_TEMPERATURE)
    OLLAMA_NUM_PREDICT = int_setting(settings.get("ollama_num_predict"), OLLAMA_NUM_PREDICT, 256)
    if settings.get("ai_provider"):
        AI_PROVIDER = str(settings["ai_provider"]).lower().strip()
    if settings.get("ai_cloud_model"):
        AI_CLOUD_MODEL = str(settings["ai_cloud_model"]).strip()
    if settings.get("anthropic_api_key") is not None:
        ANTHROPIC_API_KEY = str(settings["anthropic_api_key"])
    if settings.get("openai_api_key") is not None:
        OPENAI_API_KEY = str(settings["openai_api_key"])
    if settings.get("openai_base_url"):
        OPENAI_BASE_URL = str(settings["openai_base_url"]).rstrip("/")
    configure_ai_notes(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_CHAT_MODEL,
        max_chars=AI_NOTES_MAX_CHARS,
        timeout=OLLAMA_TIMEOUT,
        quick_model=OLLAMA_QUICK_MODEL,
        quick_timeout=OLLAMA_QUICK_TIMEOUT,
        num_ctx=OLLAMA_NUM_CTX,
        quick_num_ctx=OLLAMA_QUICK_NUM_CTX,
        temperature=OLLAMA_TEMPERATURE,
        num_predict=OLLAMA_NUM_PREDICT,
        provider=AI_PROVIDER,
        cloud_model=AI_CLOUD_MODEL,
        anthropic_api_key=ANTHROPIC_API_KEY,
        openai_api_key=OPENAI_API_KEY,
        openai_base_url=OPENAI_BASE_URL,
    )
