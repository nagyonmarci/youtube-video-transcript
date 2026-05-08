# YouTube Transcript & AI Notes

[![CI / DevSecOps](https://github.com/nagyonmarci/youtube-video-transcript/actions/workflows/ci.yml/badge.svg)](https://github.com/nagyonmarci/youtube-video-transcript/actions/workflows/ci.yml)

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

All configuration lives in `.env` (git-ignored). Copy `.env.example` and set every value marked as required.

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
| `OLLAMA_BASE_URL` | Ollama API base URL | `http://host.docker.internal:11434` |
| `OLLAMA_CHAT_MODEL` | Chat model for AI notes | `gemma4:31b-mlx-bf16` |
| `AI_NOTES_AUTO` | Auto-generate notes after each transcript | `true` |
| `AI_NOTES_BATCH_LIMIT` | Notes generated per batch run | `10` |
| `AI_NOTES_MAX_BATCH_LIMIT` | Hard cap on batch size | `20000` |
| `AI_NOTES_YEAR_BACKFILL_ENABLED` | Keep AI notes running for missing videos in one upload year | `true` |
| `AI_NOTES_YEAR_BACKFILL_YEAR` | Upload year to continuously backfill | `2026` |
| `AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT` | Max year-backfill jobs to enqueue per refill | `50` |
| `AI_NOTES_YEAR_BACKFILL_TARGET_ACTIVE` | Target queued/running/paused AI jobs to keep available | `100` |
| `AI_NOTES_YEAR_BACKFILL_INTERVAL_SECONDS` | API scheduler refill interval | `300` |
| `AI_NOTES_YEAR_BACKFILL_IDLE_SECONDS` | AI worker idle refill throttle | `60` |
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

# Manual endpoint test (token-free health check)
docker compose exec -T fetcher curl -s http://localhost:8000/health
# or with the app token
docker compose exec -T fetcher curl -s -H "x-app-token: $(grep APP_API_TOKEN .env | cut -d= -f2)" http://localhost:8000/status
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
| yt-dlp errors or blocked requests | Outdated binary | Check version with `docker compose exec -T fetcher yt-dlp --version`; rebuild if outdated |
| Ollama connection refused | Wrong base URL or Ollama not running | Verify `OLLAMA_BASE_URL` in `.env`; `http://host.docker.internal:11434` works on Docker Desktop (Mac/Windows) |
| Whisper model not found | First-start download incomplete | Check `docker compose logs whisper`; the download retries on restart |
| Job stuck in `running` | Worker crashed mid-job | Jobs are automatically re-queued after `STALE_JOB_MINUTES`; or use the Admin dashboard to cancel manually |
| `web` network not found | Network not created | `docker network create web` |
