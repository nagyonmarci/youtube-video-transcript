# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Start everything
docker compose up -d

# Rebuild and restart a single service after code change
docker compose build fetcher && docker compose up -d fetcher
docker compose build frontend && docker compose up -d frontend

# Syntax check Python (no test suite exists)
python3 -m py_compile fetcher/*.py fetcher/routes/*.py

# Tail logs
docker compose logs -f fetcher
docker compose logs --tail=120 fetcher

# Check yt-dlp version inside container
docker compose exec -T fetcher yt-dlp --version  # expected: 2025.12.08

# Hit fetcher endpoints manually
docker compose exec -T frontend wget -qO- --header="X-App-Token: $APP_API_TOKEN" http://fetcher:8000/status
```

The app runs at **http://yt.test** (requires dnsmasq; see README).  
The Caddy entrypoint is protected by Basic Auth. Directus is intentionally not exposed through `yt.test`; access it only from the Docker network or add a temporary local-only route when needed.

## Architecture

```
http://yt.test
      │
   Caddy ──► Frontend (Astro+React preview :4321)
      │
      ├─ /api     ──► Fetcher :8000 ──► Directus :8055 ──► PostgreSQL
      └─ /whisper ──► Whisper :8001 ──► Directus :8055
```

Core Docker services: `postgres`, `directus`, `fetcher`, `fetch-worker`, `ai-worker`, `whisper`, `frontend`, `caddy`.

## Data Model

All persistent state lives in Directus (PostgreSQL). Three key collections:

- **`channels`** – YouTube channels (`channel_url`, `channel_handle`, `status`, `last_refreshed`)
- **`videos`** – per-video records (`video_id`, `channel_id`, `transcript`, `transcript_timed`, `uploaded_at`, `status`, AI note fields)
- **`jobs`** – persistent work queue (`queue`, `type`, `status`, `payload`, `sort_order`)

Schema is bootstrapped at fetcher startup via `DirectusClient.ensure_schema()` — it creates missing collections and fields programmatically. No SQL migrations exist.

## Fetcher Service (`fetcher/`)

FastAPI app with **three background worker loops** polling the `jobs` Directus collection:

- `worker_loop` — processes `fetch` queue: `channel`, `video`, `refresh`, `refresh_dates`, `refresh_thumbnails`
- `quick_worker_loop` — processes `quick` queue: fast one-paragraph summary (Phase 1)
- `ai_worker_loop` — processes `ai` queue: `ai_notes`, `ai_note_video`

Workers are separated so LLM calls (Ollama) never block transcript fetching. All workers restart cleanly on stop/cancel — see `restart_ai_worker()` and the `/stop` endpoint.

Key modules:
- `main.py` — FastAPI app init, lifespan, middleware, router wiring (~78 lines)
- `config.py` — env var parsing, settings hot-reload (`apply_app_settings`)
- `db.py` — asyncpg pool, index bootstrap
- `worker_state.py` — global stop flags, task state dicts, ContextVars, directus instance
- `job_utils.py` — job claim (`FOR UPDATE SKIP LOCKED`), progress, heartbeat, retry, deduplication
- `job_ops.py` — enqueue helpers, cancel, cleanup, year-backfill
- `fetch_tasks.py` — channel/video/refresh task handlers
- `ai_tasks.py` — AI notes and quick-summary task handlers
- `workers.py` — worker loops, handler registry, bootstrap, `run_worker_service`
- `scheduler.py` — APScheduler setup, daily refresh
- `api_models.py` — Pydantic request models
- `routes/` — FastAPI APIRouters: `status.py`, `jobs.py`, `ui.py`, `fetch.py`, `ai.py`
- `directus_client.py` — all Directus REST calls; schema bootstrap; job CRUD
- `youtube_fetcher.py` — yt-dlp and youtube-transcript-api wrappers; rate-limited sleep helpers
- `ai_notes.py` — Ollama/cloud chat call; `build_prompt()`; `extract_json()`; `normalize_list()`

Rate limits are enforced inside `youtube_fetcher.py` (`rate_limited_sleep_transcript`: 45–75 s, `rate_limited_sleep_channel`: 5–15 s).

## Frontend (`frontend/`)

Astro shell (`src/pages/index.astro`) that mounts a single React SPA (`src/App.jsx`). All interactivity is React; Astro is only used for the HTML shell and Vite/dev-server.

**Data access split:**
- `src/lib/directus.js` — reads/writes UI data through fetcher facade endpoints under `/api/ui/*`; no Directus token is exposed to the browser
- `src/lib/fetcher.js` — all write/action calls go through the Fetcher API (`/api/...`)
- `src/lib/export.js` — pure client-side export helpers (TXT, MD, Obsidian MD, Markmap MD); no network calls

**Key components:**
- `App.jsx` — top-level state (channels, videos, selected video, view routing, status polling)
- `ChannelGrid.jsx` / `ChannelSidebar.jsx` — channel list/selection
- `VideoTable.jsx` — paginated video list with sort/search/export/AI note buttons
- `TranscriptModal.jsx` — full transcript view + export buttons
- `AdminDashboard.jsx` — job queue management (pause/resume/move/delete jobs)
- `DailyUpdatesPage.jsx` — videos grouped by upload date

## AI Notes Pipeline

1. After a transcript is fetched, `enqueue_ai_note()` creates an `ai_note_video` job in the `ai` queue
2. `ai_worker_loop` picks it up and calls `generate_and_store_ai_notes()`
3. `ai_notes.py::generate_ai_notes()` calls Ollama (`OLLAMA_CHAT_MODEL`, default `gemma4:31b-mlx-bf16`) and returns `{summary, topics, takeaways, questions, obsidian_note}`
4. `obsidian_note` is markmap-compatible: starts with `# Title`, uses `## Section` + `- bullets` only
5. Frontend can export per-video markmap files via `videoToMarkmapMd()` in `export.js`
6. The year backfill loop keeps enqueueing missing AI notes for `AI_NOTES_YEAR_BACKFILL_YEAR` (default `2026`) until every eligible video from that upload year has notes.

## Job Queue Patterns

- `enqueue_fetch_job(task)` / `enqueue_ai_job(task)` — create jobs; return the created job dict (includes `id`)
- `dedupe_key` on queued jobs prevents duplicate work at enqueue time
- SQL lock based claiming prevents multiple workers from taking the same job
- `cancel_jobs(queue, predicate)` — batch cancel; used by `/stop`
- Job `sort_order`, `progress_current`, `progress_total`, `progress_message`, `locked_by`, and `locked_at` drive priority, status, and UI progress

## Workflow Notes

- Enter plan mode for any task with 3+ steps or architectural decisions
- After schema-touching changes to `directus_client.py`: the new fields only appear after `docker compose up -d fetcher` (schema bootstrap runs on startup)
- No full test suite — verify with `py_compile`, `npm run build`, `npm audit --omit=dev`, `docker compose config --quiet`, manual HTTP checks, and log inspection
- Browser code must not call Directus directly or contain static service tokens
