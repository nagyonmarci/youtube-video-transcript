// Domain types mirroring the Directus schema bootstrapped by
// fetcher/directus_client.py::ensure_schema() and the fetcher/whisper
// status endpoints (fetcher/routes/status.py, whisper/main.py).

export interface Channel {
  id: string;
  name: string | null;
  topic: string | null;
  channel_url: string | null;
  channel_handle: string | null;
  added_at: string | null;
  status: 'pending' | 'processing' | 'done' | 'error' | null;
  video_count: number | null;
  error_message: string | null;
  last_refreshed: string | null;
}

// The fetcher's /ui/videos* facade endpoints always deep-populate channel_id
// (see fetcher/routes/ui.py UI_VIDEO_FIELDS: "channel_id.id,channel_id.name,channel_id.channel_handle").
export interface VideoChannelRef {
  id: string;
  name: string | null;
  channel_handle: string | null;
}

export interface Video {
  id: string;
  video_id: string | null;
  channel_id: VideoChannelRef | null;
  whisper_status: string | null;
  title: string | null;
  url: string | null;
  thumbnail_url: string | null;
  is_members_only: boolean | null;
  duration_seconds: number | null;
  uploaded_at: string | null;
  transcript: string | null;
  transcript_timed: string | null;
  summary: string | null;
  topics: string[] | null;
  takeaways: string[] | null;
  questions: string[] | null;
  obsidian_note: string | null;
  study_guide: string | null;
  critique: string | null;
  quick_summary: string | null;
  quick_summary_model: string | null;
  quick_summary_generated_at: string | null;
  ai_notes_status: 'pending' | 'done' | 'error' | null;
  ai_notes_generated_at: string | null;
  ai_notes_error: string | null;
  status: 'pending' | 'done' | 'no_transcript' | 'error' | null;
  processed_at: string | null;
}

export interface PaginatedVideos {
  items: Video[];
  total: number;
}

// The narrower field set fetcher/routes/ui.py's /ui/error-videos returns.
export interface ErrorVideoSummary {
  id: string;
  video_id: string | null;
  title: string | null;
  url: string | null;
  channel_id: Pick<VideoChannelRef, 'name' | 'channel_handle'> | null;
}

export interface AdminStats {
  totalVideos: number;
  todayVideos: number;
  errorVideos: number;
  missingTranscripts: number;
  missingAiNotes: number;
}

export interface MonthlyVideoCount {
  month: string;
  count: number;
}

export interface ChannelCoverageMaps {
  totalMap: Map<string, number>;
  transcriptMap: Map<string, number>;
  aiMap: Map<string, number>;
}

// UI-only: components attach the selected channel onto the video they
// picked (see App.jsx/DailyApp.jsx/SearchApp.jsx onSelectVideo) so
// TranscriptModal/export.js have a channel name/handle without a lookup.
export type SelectedVideo = Video & { channel?: Channel | VideoChannelRef | null };

export type JobQueue = 'fetch' | 'quick' | 'ai' | 'whisper';
export type JobStatus = 'queued' | 'running' | 'paused' | 'done' | 'error' | 'cancelled';

// AI-note job timing breakdown; fields set by the ai_note_video task handler
// as it goes through each phase (all optional/absent for non-AI jobs).
export interface JobMetrics {
  ollama_load_seconds?: number;
  first_token_seconds?: number;
  prompt_eval_seconds?: number;
  eval_seconds?: number;
  json_parse_seconds?: number;
  eval_tokens_per_second?: number;
}

export interface Job {
  id: string;
  queue: JobQueue;
  type: string;
  label: string | null;
  status: JobStatus;
  sort_order: number | null;
  payload: Record<string, unknown> | null;
  dedupe_key: string | null;
  attempts: number | null;
  max_attempts: number | null;
  progress_current: number | null;
  progress_total: number | null;
  progress_label: string | null;
  locked_at: string | null;
  locked_by: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  last_error: string | null;
  duration_seconds: number | null;
  metrics: JobMetrics | null;
}

export interface CurrentTask {
  type?: string | null;
  phase?: string | null;
  video?: string | null;
  video_id?: string | null;
  job_id?: string | null;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_label?: string | null;
  started_at?: string | null;
  duration_seconds?: number | null;
  metrics?: Record<string, unknown> | null;
}

// fetcher/routes/status.py::get_ollama_resource_status()
export interface OllamaModel {
  name: string | null;
  model: string | null;
  size: number;
  size_vram: number;
  processor_percent: number | null;
  context_length: number | null;
  expires_at: string | null;
  parameter_size: string | null;
  quantization_level: string | null;
}

export interface OllamaStatus {
  online: boolean;
  base_url: string;
  configured_model: string;
  models: OllamaModel[];
  sampled_at: string;
  error: string | null;
}

export interface QueueCounts {
  queued: number;
  running: number;
  paused: number;
  error: number;
  active: number;
}

export interface Schedule {
  cron: string;
  timezone: string;
}

export interface FetcherStatus {
  queue_size: number;
  quick_queue_size: number;
  ai_queue_size: number;
  fetch_active_size: number;
  quick_active_size: number;
  ai_active_size: number;
  queues: { fetch: QueueCounts; quick: QueueCounts; ai: QueueCounts };
  workers: { fetch_concurrency: number; quick_concurrency: number; ai_concurrency: number };
  stopped_queues: { fetch: boolean; quick: boolean; ai: boolean };
  current_task: CurrentTask | Record<string, never>;
  current_quick_task: CurrentTask | Record<string, never>;
  current_ai_task: CurrentTask | Record<string, never>;
  resources: {
    ai_worker_enabled: boolean;
    ai_job_cooldown_seconds: number;
    ai_worker_concurrency: number;
    ai_queue: QueueCounts;
    ollama: OllamaStatus;
  };
  schedule: Schedule;
  ai_year_backfill: {
    enabled: boolean;
    year: number;
    missing: number | null;
    target_active: number;
    batch_limit: number;
    interval_seconds: number;
  };
}

// Normalized shape produced by AdminDashboard's normalizeSettings(); mirrors
// fetcher/config.py::current_app_settings().
export interface AppSettings {
  ollama_base_url: string;
  ollama_chat_model: string;
  ollama_timeout: number;
  ai_notes_max_chars: number;
  ai_notes_auto: boolean;
  ai_notes_batch_limit: number;
  ai_notes_max_batch_limit: number;
  ai_notes_year_backfill_enabled: boolean;
  ai_notes_year_backfill_year: number;
  ai_notes_year_backfill_batch_limit: number;
  ai_notes_year_backfill_target_active: number;
  ai_notes_year_backfill_interval_seconds: number;
  ai_notes_year_backfill_idle_seconds: number;
  ai_notes_worker_enabled: boolean;
  ai_notes_job_cooldown_seconds: number;
  ai_notes_quick_enabled: boolean;
  ollama_quick_model: string;
  ollama_quick_timeout: number;
  ollama_num_ctx: number;
  ollama_quick_num_ctx: number;
  ollama_temperature: number;
  ollama_num_predict: number;
  ai_provider: string;
  ai_cloud_model: string;
  anthropic_api_key: string;
  openai_api_key: string;
  openai_base_url: string;
  ai_night_window_enabled: boolean;
  ai_night_window_start_hour: number;
  ai_night_window_stop_hour: number;
}

export interface WhisperStatus {
  queue_size: number;
  stop_flag: boolean;
  batch_running: boolean;
  current_task: CurrentTask | Record<string, never>;
}
