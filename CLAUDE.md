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

# Hit fetcher endpoints manually (fetcher has curl; frontend/fetcher images are minimal and have no wget)
docker compose exec -T fetcher curl -sS -H "X-App-Token: $APP_API_TOKEN" http://localhost:8000/status
```

`frontend` and `fetcher`/`fetch-worker`/`ai-worker` build on Chainguard's Wolfi-based images (multi-stage: a `-dev` builder stage, a minimal runtime stage). The shipped `frontend` image has a shell but no `wget`/`curl`/`npm`-as-CLI-tool network debugging; `fetcher`'s runtime stage is `wolfi-base` rather than a stripped image, so besides `curl`/`ffmpeg` (added explicitly for app needs) it still has `apk` available too (confirmed via `docker run --entrypoint sh`). There is no `-dev`-tagged variant of these *built* images — for deeper interactive debugging, run the relevant base image directly, e.g. `docker run --rm -it cgr.dev/chainguard/wolfi-base sh`.

The app runs at **http://yt.test** (requires dnsmasq; see README).  
The Caddy entrypoint is protected by Basic Auth. Postgres itself is not exposed through `yt.test`; access it only from the Docker network (`docker compose exec postgres psql -U directus`) or add a temporary local-only route when needed.

## Architecture

```
http://yt.test
      │
   Caddy ──► Frontend (Astro+React preview :4321)
      │
      ├─ /api     ──► Fetcher :8000 ──► PostgreSQL
      └─ /whisper ──► Whisper :8001 ──► PostgreSQL
```

Core Docker services: `postgres`, `fetcher`, `fetch-worker`, `ai-worker`, `whisper`, `frontend`, `caddy`.

## Data Model

All persistent state lives directly in PostgreSQL — the fetcher and whisper services talk to it via `asyncpg`, no ORM. Three key tables:

- **`channels`** – YouTube channels (`channel_url`, `channel_handle`, `status`, `last_refreshed`)
- **`videos`** – per-video records (`video_id`, `channel_id`, `transcript`, `transcript_timed`, `uploaded_at`, `status`, AI note fields)
- **`jobs`** – persistent work queue (`queue`, `type`, `status`, `payload`, `sort_order`)

Schema is bootstrapped at fetcher startup via `schema.py::ensure_schema()` — idempotent `CREATE TABLE IF NOT EXISTS`/`ALTER TABLE ADD COLUMN IF NOT EXISTS` statements. No SQL migrations exist.

## Fetcher Service (`fetcher/`)

FastAPI app with **three background worker loops** polling the `jobs` table:

- `worker_loop` — processes `fetch` queue: `channel`, `video`, `refresh`, `refresh_dates`, `refresh_thumbnails`
- `quick_worker_loop` — processes `quick` queue: fast one-paragraph summary (Phase 1)
- `ai_worker_loop` — processes `ai` queue: `ai_notes`, `ai_note_video`

Workers are separated so LLM calls (Ollama) never block transcript fetching. All workers restart cleanly on stop/cancel — see `restart_ai_worker()` and the `/stop` endpoint.

Key modules:
- `main.py` — FastAPI app init, lifespan, middleware, router wiring (~78 lines)
- `config.py` — env var parsing, settings hot-reload (`apply_app_settings`)
- `db.py` — asyncpg pool, index bootstrap
- `schema.py` — idempotent table/column DDL bootstrap (`ensure_schema()`)
- `worker_state.py` — global stop flags, task state dicts, ContextVars, `directus` instance (the shared `PostgresClient`)
- `job_utils.py` — job claim (`FOR UPDATE SKIP LOCKED`), progress, heartbeat, retry, deduplication
- `job_ops.py` — enqueue helpers, cancel, cleanup, year-backfill
- `fetch_tasks.py` — channel/video/refresh task handlers
- `ai_tasks.py` — AI notes and quick-summary task handlers
- `workers.py` — worker loops, handler registry, bootstrap, `run_worker_service`
- `scheduler.py` — APScheduler setup, daily refresh
- `api_models.py` — Pydantic request models
- `routes/` — FastAPI APIRouters: `status.py`, `jobs.py`, `ui.py`, `fetch.py`, `ai.py`
- `pg_client.py` — `PostgresClient`: all channel/video/job/setting CRUD via `asyncpg`
- `youtube_fetcher.py` — yt-dlp and youtube-transcript-api wrappers; rate-limited sleep helpers
- `ai_notes.py` — Ollama/cloud chat call; `build_prompt()`; `extract_json()`; `normalize_list()`

Rate limits are enforced inside `youtube_fetcher.py` (`rate_limited_sleep_transcript`: 45–75 s, `rate_limited_sleep_channel`: 5–15 s).

## Frontend (`frontend/`)

Astro shell (`src/pages/index.astro`) that mounts a single React SPA (`src/App.jsx`). All interactivity is React; Astro is only used for the HTML shell and Vite/dev-server.

**Data access split:**
- `src/lib/directus.js` — reads/writes UI data through fetcher facade endpoints under `/api/ui/*`; no database credentials are exposed to the browser
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

## Security & Hardening Policy

Distilled from an internal DevSecOps policy doc, scoped to what actually fits this project (single-host Docker Compose, Python/Node, no Kubernetes). Points that don't fit this project's scale are marked N/A rather than cargo-culted in — see "Not applicable" below. Status markers (`Gap:` / `Not yet applied`) reflect a point-in-time audit; re-verify before trusting them on anything security-critical.

**Containers**
- Custom Dockerfiles (`fetcher/`, `whisper/`, `frontend/`) must run as non-root. Already true for all three: `fetcher`/`fetch-worker`/`ai-worker` → `USER nonroot`; `whisper` → `USER appuser`; `frontend` → inherits UID 65532 from the base image.
- `security_opt: [no-new-privileges:true]` + `cap_drop: [ALL]` is required on every custom service in `docker-compose.yml`. Already applied to `fetcher`, `fetch-worker`, `ai-worker`, `whisper`, `frontend`. **Gap:** `postgres`, `caddy` (vendor images) have none of this — add the same two lines when next touching `docker-compose.yml`. `caddy` is the one internet-facing service (ports 80/443) and currently has zero compose-level hardening, so it's the higher-priority of the two.
- Prefer a shell-free/package-manager-free final stage. **Gap, confirmed empirically** (`docker run --entrypoint sh <image> -c '...'`): none of the three custom images currently qualify. `fetcher`'s final stage is `wolfi-base` (has `apk` + shell — see the note above); `frontend`'s final stage is Chainguard's non-dev `node:latest` but still has a shell; `whisper`'s final stage is `python:3.12-slim` (Debian, apt + shell). Closing this needs a follow-up Dockerfile rework (e.g. `fetcher` → `chainguard/python`), not done here.
- `read_only: true` root filesystem is the target for custom services, with `tmpfs` for the specific paths that need runtime writes. **Not yet applied anywhere.** What each service would need: `fetcher`/`fetch-worker`/`ai-worker` → `/tmp` (yt-dlp subtitle-fallback `tempfile.TemporaryDirectory()` in `youtube_fetcher.py`); `whisper` → `/tmp` (every transcription job calls `tempfile.mkdtemp()` in `transcriber.py` — core path, not a fallback); `frontend` → no runtime writes found, best candidate to flip first.
- Static binaries don't apply to the Python/Node services. `whisper.cpp` (C/C++, built from source in `whisper/Dockerfile`) is dynamically linked today — static linking is possible future hardening, not a requirement.
- Vendor images (`postgres:16-alpine`, `caddy:2-alpine`) are used unmodified — harden at the compose level only, never by forking their Dockerfiles.
- DB is already Postgres (`postgres` service, accessed directly via `asyncpg`) — never introduce SQLite or another embedded/file-based DB.

**Supply chain / CI**
- `npm ci` should run with `--ignore-scripts` — `frontend/package.json` has no `preinstall`/`postinstall`/`prepare` scripts, so this is safe to add. **Not yet applied** in `.github/workflows/ci.yml` (`frontend` job) or `frontend/Dockerfile`.
- pip has no direct `--ignore-scripts` equivalent — don't invent one. If tightened later, the real levers are `--require-hashes` with pinned/hashed requirements, or `--only-binary=:all:`.
- Use established, actively-maintained SCA tools — already in place: Trivy (fs/secrets + container images), `pip-audit` (both Python services), `npm audit --omit=dev`. **Do not build a custom vulnerability scanner** — maintaining an accurate, current CVE database is a project in itself that Trivy/pip-audit already solve well.
- **Gap:** the two Trivy container-image scan jobs run with `exit-code: "0"` (report-only); only the filesystem/secrets scan is blocking (`exit-code: "1"`). If vulnerable shipped images should actually block a merge, flip the image scans to `exit-code: "1"` too.
- Full SLSA Level 3 (hermetic/air-gapped builders, signed provenance) is disproportionate for this project's size and incompatible with GitHub-hosted runners as currently used — don't chase it. Realistic scoped-down target instead: set `provenance: true` and `sbom: true` on the existing `docker/build-push-action@v6` calls in `release.yml` (BuildKit supports both natively, no new infra needed). **Not yet applied.**

**AI agent behavior** (governs Claude Code and any other coding agent working in this repo)
- Only read/write within this repository and the session's explicitly declared working directories — never voluntarily read host credential stores (`~/.aws`, `~/.kube/config`, SSH keys) or unrelated projects, even where technically reachable.
- This is a behavioral rule, not a technical sandbox: actual tool/directory access is controlled by Claude Code's own settings (`.claude/settings.json`, session config), outside this file's reach. Real isolation (the agent itself running inside a disposable container/microVM) is an operator/launch-time setup, not configured for this project today.
- Prefer plain-text/Markdown/code context over image-based context when directing AI agents — already the default in this workflow, no change needed.

**Not applicable to this project**
- Kubernetes `Pod`/`SecurityContext` fields (`runAsNonRoot:`, seccomp/AppArmor profile references, etc.) don't apply literally — this stack runs on Docker Compose, not Kubernetes; the underlying principles are covered above via Compose equivalents instead.
- Docker's default seccomp profile already applies to every container here (nothing disables it) — a hand-tuned custom profile is possible future hardening, not a current gap. AppArmor enforcement depends on the Linux host kernel and is largely moot for local development on macOS.

## Workflow Notes

- Enter plan mode for any task with 3+ steps or architectural decisions
- After schema-touching changes to `fetcher/schema.py`: the new columns only appear after `docker compose up -d fetcher` (schema bootstrap runs on startup)
- No full test suite — verify with `py_compile`, `npm run build`, `npm audit --omit=dev`, `docker compose config --quiet`, manual HTTP checks, and log inspection
- Browser code must not connect to Postgres directly or contain static service tokens
