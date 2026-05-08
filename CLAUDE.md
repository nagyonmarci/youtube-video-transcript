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
python3 -m py_compile fetcher/main.py fetcher/directus_client.py fetcher/youtube_fetcher.py fetcher/ai_notes.py

# Tail logs
docker compose logs -f fetcher
docker compose logs --tail=120 fetcher

# Check yt-dlp version inside container
docker compose exec -T fetcher yt-dlp --version  # expected: 2025.12.08

# Hit fetcher endpoints manually
docker compose exec -T fetcher curl -s http://localhost:8000/status
docker compose exec -T fetcher curl -s -X POST http://localhost:8000/refresh-dates
```

The app runs at **http://yt.test** (requires dnsmasq; see README).  
Directus admin UI: **http://yt.test/admin**

## Architecture

```
http://yt.test
      │
   Caddy ──► Frontend (Astro+React :4321)
                  │  Vite dev proxy (astro.config.mjs)
                  ├─ /admin   ──► Directus :8055 ──► PostgreSQL
                  ├─ /api     ──► Fetcher :8000
                  └─ /whisper ──► Whisper :8001
```

**Five Docker services:** `postgres`, `directus`, `fetcher`, `frontend`, `caddy`. Caddy also proxies `suliweb.test` (external project) via the shared `web` Docker network.

## Data Model

All persistent state lives in Directus (PostgreSQL). Three key collections:

- **`channels`** – YouTube channels (`channel_url`, `channel_handle`, `status`, `last_refreshed`)
- **`videos`** – per-video records (`video_id`, `channel_id`, `transcript`, `transcript_timed`, `uploaded_at`, `status`, AI note fields)
- **`jobs`** – persistent work queue (`queue`, `type`, `status`, `payload`, `sort_order`)

Schema is bootstrapped at fetcher startup via `DirectusClient.ensure_schema()` — it creates missing collections and fields programmatically. No SQL migrations exist.

## Fetcher Service (`fetcher/`)

FastAPI app with **two background worker loops** polling the `jobs` Directus collection:

- `worker_loop` — processes `fetch` queue: `channel`, `video`, `refresh`, `refresh_dates`
- `ai_worker_loop` — processes `ai` queue: `ai_notes`, `ai_note_video`

Workers are separated so LLM calls (Ollama) never block transcript fetching. Both workers restart cleanly on stop/cancel — see `restart_ai_worker()` and the `/stop` endpoint.

Key modules:
- `main.py` — FastAPI app, both worker loops, all API endpoints, scheduler
- `directus_client.py` — all Directus REST calls; schema bootstrap; job CRUD
- `youtube_fetcher.py` — yt-dlp and youtube-transcript-api wrappers; rate-limited sleep helpers
- `ai_notes.py` — Ollama chat call; `build_prompt()`; `extract_json()`; `normalize_list()`

Rate limits are enforced inside `youtube_fetcher.py` (`rate_limited_sleep_transcript`: 45–75 s, `rate_limited_sleep_channel`: 5–15 s).

## Frontend (`frontend/`)

Astro shell (`src/pages/index.astro`) that mounts a single React SPA (`src/App.jsx`). All interactivity is React; Astro is only used for the HTML shell and Vite/dev-server.

**Data access split:**
- `src/lib/directus.js` — reads data directly from Directus (`/admin/items/...`) with the hardcoded admin token
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

## Job Queue Patterns

- `enqueue_fetch_job(task)` / `enqueue_ai_job(task)` — create jobs; return the created job dict (includes `id`)
- `get_active_job_by_type(queue, type)` — check for existing queued/running job before creating a duplicate
- `cancel_jobs(queue, predicate)` — batch cancel; used by `/stop`
- Job `sort_order` field controls processing priority (lower = sooner); default increments by 1000

## Workflow Notes

- Enter plan mode for any task with 3+ steps or architectural decisions
- After schema-touching changes to `directus_client.py`: the new fields only appear after `docker compose up -d fetcher` (schema bootstrap runs on startup)
- No test suite — verify with `py_compile` + manual curl + log inspection
- `DIRECTUS_TOKEN` in `frontend/src/lib/directus.js` is hardcoded to match `.env`; update both if changed
