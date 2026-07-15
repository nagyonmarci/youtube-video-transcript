"""Pydantic request models for FastAPI endpoints."""

from typing import Optional

from pydantic import BaseModel


class FetchChannelsRequest(BaseModel):
    urls: list[str]


class FetchVideoRequest(BaseModel):
    url: str
    channel_id: Optional[str] = None


class ScheduleRequest(BaseModel):
    cron: str
    timezone: str


class AppSettingsRequest(BaseModel):
    ollama_base_url: Optional[str] = None
    ollama_chat_model: Optional[str] = None
    ollama_timeout: Optional[int] = None
    ai_notes_max_chars: Optional[int] = None
    ai_notes_auto: Optional[bool] = None
    ai_notes_batch_limit: Optional[int] = None
    ai_notes_max_batch_limit: Optional[int] = None
    ai_notes_year_backfill_enabled: Optional[bool] = None
    ai_notes_year_backfill_year: Optional[int] = None
    ai_notes_year_backfill_batch_limit: Optional[int] = None
    ai_notes_year_backfill_target_active: Optional[int] = None
    ai_notes_year_backfill_interval_seconds: Optional[int] = None
    ai_notes_year_backfill_idle_seconds: Optional[int] = None
    ai_notes_worker_enabled: Optional[bool] = None
    ai_notes_job_cooldown_seconds: Optional[int] = None
    ai_notes_quick_enabled: Optional[bool] = None
    ollama_quick_model: Optional[str] = None
    ollama_quick_timeout: Optional[int] = None
    ollama_num_ctx: Optional[int] = None
    ollama_quick_num_ctx: Optional[int] = None
    ollama_temperature: Optional[float] = None
    ollama_num_predict: Optional[int] = None
    ai_provider: Optional[str] = None
    ai_cloud_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    ai_night_window_enabled: Optional[bool] = None
    ai_night_window_start_hour: Optional[int] = None
    ai_night_window_stop_hour: Optional[int] = None
    channel_job_video_cap: Optional[int] = None
    channel_backlog_window_enabled: Optional[bool] = None
    channel_backlog_start_hour: Optional[int] = None
    channel_backlog_stop_hour: Optional[int] = None


class AiNotesRequest(BaseModel):
    limit: Optional[int] = None


class ChannelAiNotesRequest(BaseModel):
    limit: int = 500


class AiNoteRegenerateRequest(BaseModel):
    fields: list[str]


class JobMoveRequest(BaseModel):
    direction: str
