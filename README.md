# YouTube Transcript & AI Notes

A self-hosted tool for downloading, searching, and AI-annotating YouTube channel transcripts. If a video has no available caption track, Whisper.cpp transcribes the audio automatically.

## Features

- Add channels by URL, `@handle`, or bulk `.txt`/`.csv` upload
- Add individual videos with automatic channel detection
- Infinite-scroll video list with full-text search, sort, and filters (transcript status, AI notes status, members-only)
- Export transcripts per-video, per-channel, or in bulk — TXT, MD, or Obsidian-compatible MD
- Obsidian export with YAML frontmatter, clickable timestamped transcript links back to YouTube
- AI notes per video: summary, topics, takeaways, questions, study guide, critique, and markmap-compatible Obsidian note — generated via Ollama
- AI fields are regenerable individually; AI processing runs on a separate queue and never blocks transcript fetching
- Whisper fallback runs on a nightly cron (configurable) or on-demand from the header
- Admin dashboard shows both job queues (fetch + AI), running/stuck jobs, and allows pause/resume/delete
- Daily automatic channel refresh (default: 07:00 `Europe/Budapest`)
- UI language toggle: English / Hungarian (persisted in `localStorage`)

## Architecture

```
http://yt.test
      │
   Caddy ──► Frontend (Astro+React :4321)
                  │  Vite dev proxy
                  ├─ /admin   ──► Directus :8055 ──► PostgreSQL
                  ├─ /api     ──► Fetcher   :8000
                  └─ /whisper ──► Whisper   :8001

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

App: **http://yt.test** — Directus admin: **http://yt.test/admin**

> First start: Whisper downloads `ggml-large-v3.bin` (~3 GB) to a Docker volume. This happens once.

## Configuration

All configuration lives in `.env` (git-ignored). Copy `.env.example` and set every value marked as required.

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password | `directus` (**change**) |
| `DIRECTUS_SECRET` | Directus JWT signing secret | `change-me-random-string` (**change**) |
| `DIRECTUS_ADMIN_EMAIL` | Directus admin login email | `admin@example.com` |
| `DIRECTUS_ADMIN_PASSWORD` | Directus admin UI password | `admin` (**change**) |
| `DIRECTUS_ADMIN_TOKEN` | Static API token for all internal services | `admin-token-change-me` (**change**) |
| `REFRESH_CRON` | Automatic channel refresh schedule | `0 7 * * *` |
| `SCHEDULER_TIMEZONE` | Cron timezone | `Europe/Budapest` |
| `OLLAMA_BASE_URL` | Ollama API base URL | `http://host.docker.internal:11434` |
| `OLLAMA_CHAT_MODEL` | Chat model for AI notes | `gemma4:31b-mlx-bf16` |
| `AI_NOTES_AUTO` | Auto-generate notes after each transcript | `true` |
| `AI_NOTES_BATCH_LIMIT` | Notes generated per batch run | `10` |
| `AI_NOTES_MAX_BATCH_LIMIT` | Hard cap on batch size | `20000` |
| `FETCH_WORKER_CONCURRENCY` | Parallel fetch-worker threads | `1` |
| `AI_WORKER_CONCURRENCY` | Parallel AI-worker threads | `1` |
| `STALE_JOB_MINUTES` | Re-queue jobs stuck in `running` after N minutes | `30` |
| `JOB_CLEANUP_DAYS` | Auto-delete completed/cancelled jobs after N days | `7` |
| `WHISPER_THREADS` | CPU threads for Whisper | `4` |
| `WHISPER_LANGUAGE` | Recognition language (`auto` detects) | `auto` |
| `WHISPER_BATCH_CRON` | Nightly Whisper batch schedule | `0 3 * * *` |
| `WHISPER_BATCH_LIMIT` | Max videos per Whisper batch | `50` |

## Development Workflow

```bash
# Rebuild and restart a single service after code change
docker compose build fetcher && docker compose up -d fetcher

# Tail logs
docker compose logs -f fetcher
docker compose logs --tail=120 fetch-worker

# Syntax-check Python (no test suite exists)
python3 -m py_compile fetcher/main.py fetcher/directus_client.py fetcher/youtube_fetcher.py fetcher/ai_notes.py

# Check yt-dlp version inside container
docker compose exec -T fetcher yt-dlp --version   # expected: 2025.12.08

# Manual endpoint test
docker compose exec -T fetcher curl -s http://localhost:8000/status
docker compose exec -T fetcher curl -s -X POST http://localhost:8000/refresh-dates
```

> **Schema changes:** After touching `directus_client.py`, new fields only appear once the fetcher restarts (`docker compose up -d fetcher`) — schema bootstrap runs at startup.

After switching the Ollama model, restart both workers:
```bash
docker compose up -d fetcher fetch-worker ai-worker
```

## Job Queue

The `jobs` Directus collection is the shared work queue. Two separate workers poll it:

- `fetch-worker` — `fetch` queue: channel refresh, video fetch, metadata backfill, date backfill
- `ai-worker` — `ai` queue: per-video AI note generation

Jobs have deduplication keys, retry counters, SQL-lock-based claiming (a job can only be claimed by one worker at a time), and progress tracking. A channel refresh error on one video does not stop the rest.

`FETCH_WORKER_CONCURRENCY` and `AI_WORKER_CONCURRENCY` increase parallelism — raise them only where the bottleneck (YouTube rate limits or LLM throughput) allows.

## Rate Limiting

Limits are enforced inside `youtube_fetcher.py`:

- Between transcript fetches: 45–75 s (randomised)
- Between channel list requests: 5–15 s

## Security Posture

This tool is designed for **single-user, local-network or loopback-only** deployment. The notes below describe the current posture honestly and give a hardening checklist for anyone who needs stricter controls.

### What is protected

| Control | How |
|---|---|
| Secrets at rest | `.env` is git-ignored; credentials never committed |
| TLS certificates | `certs/` is git-ignored; mkcert-generated |
| YouTube auth cookies | `cookie.txt` is git-ignored |
| Internal network isolation | All services communicate on the internal `app-network`; no service ports are bound to the host except Caddy (80, 443) |
| Single ingress | Caddy is the only externally reachable entry point |

### Known limitations (accepted for single-user use)

| Finding | Location | Notes |
|---|---|---|
| No authentication on the Fetcher API | `fetcher/main.py` | All `/api/*` endpoints are open; intended for localhost/LAN only |
| CORS `allow_origins=["*"]` | `fetcher/main.py` | Permissive; safe when not exposed to the public internet |
| Admin token in client-side JS | `frontend/src/lib/directus.js` | Token is visible in browser DevTools; acceptable when the admin is the only user |
| All internal services share one admin token | `docker-compose.yml` | No role separation; fine for a personal tool, not for multi-user |
| Containers run as root | `fetcher/Dockerfile`, `frontend/Dockerfile` | No non-root user defined |
| Directus `CORS_ORIGIN: "true"` | `docker-compose.yml` | Allows any origin to call Directus directly; safe only on loopback |
| Dev servers in containers | `frontend/Dockerfile` | Runs Astro dev server with `--host`, not a production build |
| No CI/CD or image scanning | — | No automated vulnerability scanning |
| Weak example defaults | `.env.example` | All placeholder values must be changed before first run |

### Hardening checklist (for public or multi-user deployments)

- [ ] **Rotate all credentials** — generate random `POSTGRES_PASSWORD`, `DIRECTUS_SECRET`, `DIRECTUS_ADMIN_PASSWORD`, and `DIRECTUS_ADMIN_TOKEN` before first start
- [ ] **Add API authentication** — add an `X-API-Key` or JWT middleware to `fetcher/main.py` and pass the key from the frontend
- [ ] **Restrict CORS** — change `allow_origins=["*"]` to the specific frontend origin; set `CORS_ORIGIN` in Directus to the same value
- [ ] **Create a read-only Directus token** for the frontend and a separate write token for the fetcher (instead of sharing the admin token)
- [ ] **Add non-root users to Dockerfiles** — `RUN adduser --disabled-password appuser && USER appuser`
- [ ] **Build the frontend for production** — replace `npm run dev` with `npm run build && npx astro preview` (or a static file server)
- [ ] **Pin dependency versions** — lock `requirements.txt` with exact versions and run `pip-audit` or Trivy in CI
- [ ] **Scan images** — add `trivy image` or `grype` to a CI step before deployment
- [ ] **Set up real TLS** — replace mkcert certs with Let's Encrypt (Caddy handles this automatically with a public domain)
- [ ] **Restrict Directus `CORS_ORIGIN`** — set to the specific public domain instead of `"true"`
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
| yt-dlp errors or blocked requests | Outdated binary | Check version with `docker compose exec -T fetcher yt-dlp --version`; rebuild if outdated |
| Ollama connection refused | Wrong base URL or Ollama not running | Verify `OLLAMA_BASE_URL` in `.env`; `http://host.docker.internal:11434` works on Docker Desktop (Mac/Windows) |
| Whisper model not found | First-start download incomplete | Check `docker compose logs whisper`; the download retries on restart |
| Job stuck in `running` | Worker crashed mid-job | Jobs are automatically re-queued after `STALE_JOB_MINUTES`; or use the Admin dashboard to cancel manually |
| `web` network not found | Network not created | `docker network create web` |
