# YouTube Transcript & AI Notes

[![CI / DevSecOps](https://github.com/nagyonmarci/youtube-video-transcript/actions/workflows/ci.yml/badge.svg)](https://github.com/nagyonmarci/youtube-video-transcript/actions/workflows/ci.yml)

A self-hosted tool for downloading, searching, and AI-annotating YouTube channel transcripts. If a video has no available caption track, Whisper.cpp transcribes the audio automatically.

## Features

- Add channels by URL, `@handle`, or bulk `.txt`/`.csv` upload
- Add individual videos with automatic channel detection
- Infinite-scroll video list with full-text search, sort, and filters (transcript status, AI notes status, members-only)
- Export transcripts per-video, per-channel, or in bulk — TXT, MD, or Obsidian-compatible MD
- Obsidian export with YAML frontmatter, clickable timestamped transcript links back to YouTube
- AI notes per video: summary, topics, takeaways, questions, study guide, critique, and markmap-compatible Obsidian note
- Two-phase AI pipeline: Phase 1 generates a quick summary (default model: `llama3.2`, configurable in Admin → Setup); Phase 2 produces full structured notes via the configured provider
- AI provider is user-selectable: local Ollama (default), Anthropic Claude, or any OpenAI-compatible API — configured in **Admin → Setup**, no container restart needed
- AI fields are regenerable and editable inline: quick summary and full AI notes (summary, topics, takeaways, questions) can be edited directly in the transcript modal
- Whisper fallback runs on a nightly cron (configurable) or on-demand from the header
- Admin dashboard shows all three job queues (Fetch / Quick Summary / AI Notes) with independent Stop/Start controls per queue, running/stuck jobs, per-job runtime/duration, and allows pause/resume/delete
- Admin resource monitor streams Ollama status live and shows loaded model, GPU/VRAM placement, AI worker state, and AI cooldown
- Channel grid with drag & drop topic editor: drag channel cards between topic groups, create new topics, rename groups inline, delete topics (moves channels to uncategorized)
- Daily automatic channel refresh (default: 07:00 `Europe/Budapest`)
- UI language toggle: English / Hungarian (persisted in `localStorage`)

## Architecture

```
http://yt.test
      │
   Caddy ──► Basic Auth ──► Frontend (Astro+React preview :4321)
                  ├─ /api     ──► Fetcher   :8000  (X-App-Token injected by Caddy)
                  └─ /whisper ──► Whisper   :8001  (X-App-Token injected by Caddy)

Directus :8055 ──► PostgreSQL
     ▲
     └── internal service-token traffic only

Fetcher API ──► jobs table ──► fetch-worker / ai-worker
```

**Eight Docker services:** `postgres`, `directus`, `fetcher` (API only), `fetch-worker`, `ai-worker`, `whisper`, `frontend`, `caddy`. Workers are separated so LLM calls never block transcript fetching. Caddy also proxies `suliweb.test` via the shared external `web` Docker network.

## Quick Start

### Prerequisites

- Docker + Docker Compose
- dnsmasq for `*.test` local resolution
- External Docker network named `web`
- mkcert certificate for `suliweb.test` HTTPS (only needed if running the suliweb stack)

**dnsmasq (macOS, one-time):**
```bash
brew install dnsmasq
echo 'address=/.test/127.0.0.1' >> $(brew --prefix)/etc/dnsmasq.conf
sudo brew services start dnsmasq
sudo mkdir -p /etc/resolver
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolver/test
```

**Local TLS cert for `suliweb.test` (one-time):**
```bash
brew install mkcert && mkcert -install
mkdir -p certs
mkcert -cert-file certs/suliweb.test.pem -key-file certs/suliweb.test-key.pem suliweb.test
```

### Start

```bash
cp .env.example .env
# Edit .env — change all default credentials before first run (see Security section)
docker network create web
docker compose up -d
```

App: **http://yt.test**

The app is protected by Caddy Basic Auth. Use `APP_BASIC_AUTH_USER` and the plaintext password you generated before hashing it. Directus is intentionally not exposed through `yt.test`; access it only from the Docker network or add a temporary local-only admin route when needed.

> First start: Whisper downloads `ggml-large-v3.bin` (~3 GB) to a Docker volume. This happens once.

## Configuration

Bootstrap, secret, and container-level configuration lives in `.env` (git-ignored). Copy `.env.example` and set every value marked as required. Runtime AI/Ollama settings live in **Admin → Setup** and are stored in Directus, so they can be changed without editing `.env`.

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password | `directus` (**change**) |
| `DIRECTUS_SECRET` | Directus JWT signing secret | `change-me-random-string` (**change**) |
| `DIRECTUS_ADMIN_EMAIL` | Directus admin login email | `admin@example.com` |
| `DIRECTUS_ADMIN_PASSWORD` | Directus admin UI password | `admin` (**change**) |
| `DIRECTUS_ADMIN_TOKEN` | Static API token for internal Directus calls | random value required |
| `APP_API_TOKEN` | Internal Caddy-to-FastAPI/Whisper service token | required |
| `APP_CORS_ORIGINS` | Allowed browser origins for FastAPI services | `http://yt.test,http://localhost:4321` |
| `APP_BASIC_AUTH_USER` | Username for the Caddy gate in front of the app | required |
| `APP_BASIC_AUTH_HASH` | Caddy bcrypt hash for the Basic Auth password | required |
| `REFRESH_CRON` | Automatic channel refresh schedule | `0 7 * * *` |
| `SCHEDULER_TIMEZONE` | Cron timezone | `Europe/Budapest` |
| `FETCH_WORKER_CONCURRENCY` | Parallel fetch-worker threads | `1` |
| `QUICK_WORKER_CONCURRENCY` | Parallel quick-summary worker threads | `3` |
| `AI_WORKER_CONCURRENCY` | Parallel AI-worker threads | `1` |
| `STALE_JOB_MINUTES` | Re-queue jobs stuck in `running` after N minutes | `30` |
| `JOB_CLEANUP_DAYS` | Auto-delete completed/cancelled jobs after N days | `7` |
| `WHISPER_THREADS` | CPU threads for Whisper | `4` |
| `WHISPER_LANGUAGE` | Recognition language (`auto` detects) | `auto` |
| `WHISPER_BATCH_CRON` | Nightly Whisper batch schedule | `0 3 * * *` |
| `WHISPER_BATCH_LIMIT` | Max videos per Whisper batch | `50` |
| `AI_NIGHT_WINDOW_ENABLED` | Enable automatic full-speed AI window | `true` |
| `AI_NIGHT_WINDOW_START_HOUR` | Hour to enable full-speed AI (0–23) | `17` |
| `AI_NIGHT_WINDOW_STOP_HOUR` | Hour to restore day settings (0–23) | `7` |

At `AI_NIGHT_WINDOW_START_HOUR` (default 17:00) the scheduler writes `ai_notes_auto=true`, `cooldown=0`, `ai_notes_year_backfill_enabled=true` to Directus and reloads config. At `AI_NIGHT_WINDOW_STOP_HOUR` (default 07:00) the pre-night snapshot is restored. Day settings come from **Admin → Setup** and are not affected.

AI settings are configured in **Admin → Setup** instead of `.env`: Ollama URL/model, context window (`ollama_num_ctx`, default 32 768 tokens), quick-summary context window (`ollama_quick_num_ctx`, default 4 096 tokens), temperature (default 0.1), max output tokens (`ollama_num_predict`, default 8 192), AI provider (Ollama / Anthropic / OpenAI), cloud model name, API keys, quick-summary model/timeout, AI batch limits, transcript character limit, automatic AI-after-transcript, yearly AI backfill, AI worker enable/disable, and cooldown between AI jobs. The defaults keep AI manual-only to avoid continuous GPU load.

## Development Workflow

```bash
# Rebuild and restart a single service after code change
docker compose build fetcher && docker compose up -d fetcher

# After fetcher/worker Python changes, rebuild all services that share fetcher code
docker compose build fetcher fetch-worker ai-worker && docker compose up -d fetcher fetch-worker ai-worker

# Tail logs
docker compose logs -f fetcher
docker compose logs --tail=120 fetch-worker

# Syntax-check Python (no test suite exists)
python3 -m py_compile fetcher/*.py fetcher/routes/*.py

# Check yt-dlp version inside container
docker compose exec -T fetcher yt-dlp --version   # expected: 2026.3.17

# Manual endpoint test (token-free health check)
docker compose exec -T fetcher curl -s http://localhost:8000/health
# or with the app token
docker compose exec -T fetcher curl -s -H "x-app-token: $(grep APP_API_TOKEN .env | cut -d= -f2)" http://localhost:8000/status
```

> **Schema changes:** After touching `directus_client.py`, new fields only appear once the fetcher restarts (`docker compose up -d fetcher`) — schema bootstrap runs at startup.

AI/Ollama runtime settings can be changed in **Admin → Setup**. Fetch and AI workers reload these settings before work, so changing the model, Ollama URL, AI batch size, or manual/automatic AI mode does not require a container restart.

The Admin processing screen includes a lightweight resource monitor. It uses `/api/resources/stream` for live server-sent updates and falls back to `/api/resources` polling if the stream drops. It displays Ollama reachability, the loaded model, GPU/VRAM placement, the AI worker state, worker concurrency, queued/running/paused AI job counts, and the cooldown between AI jobs. The GPU percentage comes from Ollama's model placement data (`size_vram / size`), so it tells you whether the model is resident on GPU/VRAM; it is not a native macOS compute-utilization meter.

To reduce AI load from the UI:

- Turn off **AI worker may run** to stop claiming new AI jobs. Queued AI jobs are paused and can be resumed later.
- Increase **AI cooldown between jobs** to insert a pause after each AI job. This reduces sustained load, but the running job can still use the model heavily while it is generating.
- Keep **Start AI automatically after a new transcript** off when you want fully manual AI generation.

## Release Workflow

Changes merged to `master` first pass the existing **CI / DevSecOps** workflow. After a successful CI run on `master`, the `Release` workflow automatically:

1. creates the next calendar tag, for example `v2026.05.12.1`
2. builds and publishes Docker images to GitHub Container Registry
3. creates a GitHub Release with the exact image tags

Published images:

```text
ghcr.io/nagyonmarci/youtube-video-transcript/fetcher:<tag>
ghcr.io/nagyonmarci/youtube-video-transcript/frontend:<tag>
ghcr.io/nagyonmarci/youtube-video-transcript/whisper:<tag>
```

For production-like deployments, use the normal compose file plus `docker-compose.prod.yml`. This keeps infrastructure, volumes, and environment variables from `docker-compose.yml`, but replaces local `build:` instructions with pinned release images.

```bash
RELEASE_VERSION=v2026.05.12.1 docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
RELEASE_VERSION=v2026.05.12.1 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Rollback is the same command with the previous release tag:

```bash
RELEASE_VERSION=v2026.05.11.1 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

If a release contains Directus schema changes, deploy during a quiet window and restart the dependent app services together:

```bash
RELEASE_VERSION=<tag> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d fetcher fetch-worker ai-worker frontend
```

## Job Queue

The `jobs` Directus collection is the shared work queue. Three separate queues are processed by two workers:

- `fetch-worker` — `fetch` queue: channel refresh, video fetch, metadata backfill, date backfill
- `ai-worker` — `quick` queue: fast one-paragraph summary (small model, Phase 1); then enqueues to `ai` queue
- `ai-worker` — `ai` queue: full structured notes (summary, topics, takeaways, questions, study guide, critique, Obsidian note) via the configured provider (Ollama / Anthropic / OpenAI)

Jobs have deduplication keys, retry counters, SQL-lock-based claiming (a job can only be claimed by one worker at a time), progress tracking, and runtime measurement. Worker startup re-queues jobs left behind by the same previous worker instance, and stale running jobs are re-queued periodically after `STALE_JOB_MINUTES`. Running jobs show elapsed time in the Admin dashboard, and completed jobs persist `duration_seconds` for later comparison. AI note jobs update their phase while they run (`waiting for first token`, `generating`, `parsing JSON`) and persist Ollama timing metrics in `jobs.metrics`: model load time, time to first token, prompt eval time/count, generation time/count, token throughput, prompt size, output size, and JSON parse time. The Admin job table highlights the largest AI phase as the likely bottleneck. A channel refresh error on one video does not stop the rest.

`FETCH_WORKER_CONCURRENCY`, `QUICK_WORKER_CONCURRENCY`, and `AI_WORKER_CONCURRENCY` increase parallelism — raise them only where the bottleneck (YouTube rate limits or LLM throughput) allows.

## Rate Limiting

Limits are enforced inside `youtube_fetcher.py`:

- Between transcript fetches: 45–75 s (randomised)
- Between channel list requests: 5–15 s

## Security Posture

This tool is designed for **single-user, local-network or loopback-only** deployment. The current stack now uses a single Caddy ingress, Basic Auth at the edge, and an internal app token between Caddy and the FastAPI services.

### What is protected

| Control | How |
|---|---|
| Secrets at rest | `.env` is git-ignored; credentials never committed |
| TLS certificates | `certs/` is git-ignored; mkcert-generated |
| YouTube auth cookies | `cookie.txt` is git-ignored |
| Internal network isolation | All services communicate on the internal `app-network`; no service ports are bound to the host except Caddy (80, 443) |
| Single ingress | Caddy is the only externally reachable entry point |
| Browser cannot see Directus admin token | Frontend calls `/api/ui/*`; fetcher talks to Directus server-side |
| Directus admin not publicly proxied | `/admin` is no longer routed through Caddy/frontend |
| Fetcher/Whisper API token | `/api/*` and `/whisper/*` require `X-App-Token`; Caddy injects it |
| CORS restricted | FastAPI services use `APP_CORS_ORIGINS`; Directus CORS is disabled |
| Non-root app containers | Fetcher, workers, Whisper, and frontend run as unprivileged users |
| Reduced Linux capabilities | App containers use `cap_drop: ALL` and `no-new-privileges:true` |
| Dependency audit | `npm audit --omit=dev` and `pip-audit` should be run periodically |

Generate required auth values:

```bash
APP_API_TOKEN="$(openssl rand -hex 32)"
APP_BASIC_AUTH_PASSWORD="$(openssl rand -base64 18)"
APP_BASIC_AUTH_HASH="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext "$APP_BASIC_AUTH_PASSWORD")"
```

When writing a bcrypt hash to `.env`, wrap it in single quotes because it contains `$` characters:

```bash
APP_BASIC_AUTH_HASH='$2a$14$...'
```

### Remaining limitations

| Finding | Notes |
|---|---|
| Directus internal services still use the admin token | Good enough for a personal stack, but split into least-privilege Directus roles for multi-user/public deployments |
| Caddy Basic Auth is coarse-grained | Replace with proper SSO/JWT sessions if multiple users need different permissions |
| Whisper model is downloaded at runtime | Pin and verify checksum for stricter supply-chain control |
| Whisper.cpp is cloned during image build | Pin a commit SHA and/or vendor a verified release artifact for stricter reproducibility |
| Python dependency scanning is not automated | Add `pip-audit`, Trivy, or Grype in CI |

### Hardening checklist (for public or multi-user deployments)

- [ ] **Rotate all credentials** — generate random `POSTGRES_PASSWORD`, `DIRECTUS_SECRET`, `DIRECTUS_ADMIN_PASSWORD`, `DIRECTUS_ADMIN_TOKEN`, `APP_API_TOKEN`, and Basic Auth password before first start
- [ ] **Create least-privilege Directus tokens** — separate schema bootstrap/admin operations from read/write runtime operations
- [ ] **Pin Python dependency versions** — keep `fetcher/requirements.txt` and `whisper/requirements.txt` exact and scan with `pip-audit` or Trivy
- [ ] **Scan images** — add `trivy image` or `grype` to a CI step before deployment
- [ ] **Set up real TLS** — replace mkcert certs with Let's Encrypt (Caddy handles this automatically with a public domain)
- [ ] **Add a firewall rule** — block direct access to ports 8000, 8055, 5432 from outside the host; all traffic should flow through Caddy

### Secrets never to commit

- `.env` — all credentials
- `certs/` — TLS private keys
- `cookie.txt` — YouTube session cookie

All three are covered by `.gitignore`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| New schema fields not visible | Bootstrap runs at startup | `docker compose up -d fetcher` |
| Admin data load error: `settings -> 404` | Fetcher container is running an old image without the current API routes | Rebuild/restart backend services: `docker compose build fetcher fetch-worker ai-worker && docker compose up -d fetcher fetch-worker ai-worker` |
| `/api/resources` or `/api/resources/stream` returns 404 | Same as above: frontend is newer than the fetcher image | Rebuild/restart `fetcher`, `fetch-worker`, and `ai-worker` |
| yt-dlp errors or blocked requests | Outdated binary | Check version with `docker compose exec -T fetcher yt-dlp --version`; rebuild if outdated |
| Ollama connection refused | Wrong base URL or Ollama not running | Verify the Ollama URL in **Admin → Setup**; `http://host.docker.internal:11434` works on Docker Desktop (Mac/Windows) |
| Ollama shows `100%` GPU/VRAM but fans vary | Ollama reports model placement, not live compute utilization | Use Admin → Processing for the live loaded-model/VRAM view; macOS Activity Monitor or `ollama ps` can help inspect host-side load |
| AI still uses GPU after disabling auto mode | Existing AI jobs were already queued | Use **AI worker may run** off, Stop on the AI worker line, or pause/delete queued AI jobs in Admin |
| Stop button on AI/Quick/Fetch queue has no effect | Requires fetcher rebuild after the per-queue stop-flag fix | Rebuild: `docker compose build fetcher && docker compose up -d fetcher ai-worker` |
| Whisper model not found | First-start download incomplete | Check `docker compose logs whisper`; the download retries on restart |
| Job stuck in `running` | Worker crashed mid-job | Jobs are automatically re-queued after `STALE_JOB_MINUTES`; or use the Admin dashboard to cancel manually |
| `web` network not found | Network not created | `docker network create web` |
