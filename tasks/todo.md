# Refaktor: fetcher/main.py → modulok

## Előkészítés
- [ ] `worker.py` beolvasása → milyen szimbólumokat importál `main.py`-ból
- [ ] py_compile baseline: mind a 4 meglévő .py fájl zöld

## Lépés 1 – `config.py` kiemelése
- [ ] Új fájl: `fetcher/config.py`
- [ ] Átvinni: env var globálisok, required_env, bool_setting, int_setting, get_scheduler_timezone, validate_schedule, current_app_settings, apply_app_settings, load_schedule_settings, save_schedule_settings, load_app_settings, refresh_app_settings_if_due
- [ ] main.py frissítve: from config import (...)
- [ ] Smoke test OK

## Lépés 2 – `db.py` kiemelése
- [ ] Új fájl: `fetcher/db.py`
- [ ] Átvinni: pg_pool, get_pg_pool, close_pg_pool, ensure_database_indexes
- [ ] Smoke test OK

## Lépés 3 – `worker_state.py` kiemelése
- [ ] Új fájl: `fetcher/worker_state.py`
- [ ] Átvinni: stop flag-ek, current_task_info/job_id dict-ek, ContextVar pool, directus instance
- [ ] Smoke test OK

## Lépés 4 – `job_utils.py` kiemelése
- [ ] Új fájl: `fetcher/job_utils.py`
- [ ] Átvinni: job_dedupe_key, update_job_progress, update_current_job_phase, job_status_counts, reset_stale_running_jobs_if_due, reset_stale_running_jobs, reset_owned_running_jobs, retry_or_fail_job, update_video_ai_status, heartbeat_job, normalize_claimed_job, parse_datetime, job_duration_seconds, summarize_ai_metrics, claim_next_job
- [ ] Smoke test OK

## Lépés 5 – `job_ops.py` kiemelése
- [ ] Új fájl: `fetcher/job_ops.py`
- [ ] Átvinni: enqueue_fetch_job, enqueue_ai_job, enqueue_quick_job, enqueue_ai_note, maybe_enqueue_ai_year_backfill, cancel_jobs, cleanup_orphan_ai_pending_videos, current_job_snapshot, clear_ai_notes, cleanup_old_jobs
- [ ] Smoke test OK

## Lépés 6 – `fetch_tasks.py` kiemelése
- [ ] Új fájl: `fetcher/fetch_tasks.py`
- [ ] Átvinni: _backfill_metadata, _process_channel_transcripts, process_channel_task, process_single_video_task, process_refresh_task, process_refresh_dates_task, process_refresh_thumbnails_task
- [ ] Smoke test OK

## Lépés 7 – `ai_tasks.py` kiemelése
- [ ] Új fájl: `fetcher/ai_tasks.py`
- [ ] Átvinni: generate_and_store_ai_notes, process_ai_notes_task, process_single_ai_note_task, process_quick_note_task
- [ ] Smoke test OK

## Lépés 8 – `workers.py` kiemelése
- [ ] Új fájl: `fetcher/workers.py`
- [ ] Átvinni: FETCH_HANDLERS, QUICK_HANDLERS, AI_HANDLERS, _init_handlers, worker_loop, ai_worker_loop, quick_worker_loop, restart_ai_worker, create_worker_tasks, run_worker_service
- [ ] Smoke test OK

## Lépés 9 – `scheduler.py` kiemelése
- [ ] Új fájl: `fetcher/scheduler.py`
- [ ] Átvinni: scheduler globális, start_refresh_scheduler, daily_refresh, bootstrap_runtime
- [ ] Smoke test OK

## Lépés 10 – `api_models.py` kiemelése
- [ ] Új fájl: `fetcher/api_models.py`
- [ ] Átvinni: FetchChannelsRequest, FetchVideoRequest, ScheduleRequest, AppSettingsRequest, AiNotesRequest, ChannelAiNotesRequest, AiNoteRegenerateRequest, JobMoveRequest
- [ ] Smoke test OK

## Lépés 11 – `routes/status.py` kiemelése
- [ ] Új könyvtár: `fetcher/routes/`
- [ ] Új fájl: `fetcher/routes/__init__.py`, `fetcher/routes/status.py`
- [ ] Átvinni: GET /health, /status, /resources, /resources/stream, /schedule (GET+PATCH), /settings (GET+PATCH) + UI helper függvények
- [ ] Smoke test OK

## Lépés 12 – `routes/jobs.py` kiemelése
- [ ] Új fájl: `fetcher/routes/jobs.py`
- [ ] Átvinni: GET /jobs, POST /jobs/{id}/pause|resume|start, POST /jobs/{id}/move, DELETE /jobs/{id}
- [ ] Smoke test OK

## Lépés 13 – `routes/ui.py` kiemelése
- [ ] Új fájl: `fetcher/routes/ui.py`
- [ ] Átvinni: GET /ui/channels, PATCH/DELETE /ui/channels/{id}, GET /ui/videos/*, /ui/channels/{id}/videos, /ui/admin-stats, /ui/channel-coverage, /ui/monthly-video-counts
- [ ] Smoke test OK

## Lépés 14 – `routes/fetch.py` kiemelése
- [ ] Új fájl: `fetcher/routes/fetch.py`
- [ ] Átvinni: POST /fetch-channels, /fetch-video, /refresh-channel/{id}, /refresh-dates, /refresh-thumbnails
- [ ] Smoke test OK

## Lépés 15 – `routes/ai.py` kiemelése
- [ ] Új fájl: `fetcher/routes/ai.py`
- [ ] Átvinni: POST /ai-notes, /quick-notes/{id}, /ai-notes/{id}, /ai-notes/{id}/regenerate, /channels/{id}/ai-notes, DELETE /ai-notes/{id}, POST /stop, /resume
- [ ] Smoke test OK

## Lépés 16 – `main.py` elvékonyítása
- [ ] main.py: csak FastAPI app init, lifespan, middleware, router include-ok (≤ 100 sor)
- [ ] Smoke test OK
- [ ] main.py ≤ 100 sor ellenőrzés

## Phase 5 – Verifikáció
- [ ] python3 -m py_compile fetcher/*.py fetcher/routes/*.py — zöld
- [ ] docker compose build fetcher — sikeres
- [ ] docker compose up -d fetcher + log ellenőrzés — schema bootstrap + worker start OK
- [ ] GET /health, GET /status — 200 OK
- [ ] Before/after metrikák dokumentálva
