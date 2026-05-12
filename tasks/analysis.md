# main.py Strukturális és Kockázati Analízis

## 1. Inventárium

### 1.1. Environment / Config (1-112 sorok)

**Importok:**
- `asyncio`, `json`, `logging`, `os`, `socket`, `time`
- `contextvars.ContextVar` – context-local storage worker threadekhez
- `datetime`, `timezone`, `timedelta`, `ZoneInfo`
- `apscheduler.schedulers.asyncio.AsyncIOScheduler`
- `fastapi`, `fastapi.middleware.cors`, `fastapi.responses`
- `pydantic.BaseModel`
- `asyncpg` – Postgres async driver
- `httpx` – async HTTP client
- Saját modulok: `ai_notes`, `constants`, `directus_client`, `youtube_fetcher`

**Globális konstansok (sorok 59-111):**
- `DIRECTUS_URL`, `DIRECTUS_TOKEN`, `APP_API_TOKEN`
- `APP_CORS_ORIGINS` – CORS whitelist
- `POSTGRES_*` – Postgres connection params
- `REFRESH_CRON`, `SCHEDULER_TIMEZONE` – cron schedule + timezone
- AI konfigurációk: `AI_NOTES_AUTO`, `AI_NOTES_BATCH_LIMIT`, `AI_NOTES_MAX_BATCH_LIMIT`, `AI_NOTES_YEAR_BACKFILL_*`
- `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_TIMEOUT`, `OLLAMA_QUICK_MODEL`, `OLLAMA_QUICK_TIMEOUT`
- AI provider választó: `AI_PROVIDER` (ollama|anthropic|openai), `AI_CLOUD_MODEL`, API keys
- Worker konfigurációk: `FETCHER_ROLE` (api|worker|all), `WORKER_QUEUES`, `FETCH_WORKER_CONCURRENCY`, `QUICK_WORKER_CONCURRENCY`, `AI_WORKER_CONCURRENCY`
- `STALE_JOB_MINUTES`, `JOB_CLEANUP_DAYS`, `WORKER_ID` (hostname:pid vagy custom)

**Helper funkciók (sorok 59-169):**
- `required_env(name: str) -> str` – szükséges env var vagy RuntimeError
- `get_scheduler_timezone()` – ZoneInfo vagy UTC fallback
- `validate_schedule(cron: str, timezone_name: str)` – cron + timezone validáció
- `bool_setting(value) -> bool` – stringből bool (1|true|yes|on)
- `int_setting(value, default, minimum, maximum) -> int` – bounded int parsing

### 1.2. App Settings Management (sorok 182-301)

**Funkciók:**
- `current_app_settings() -> dict` – snapshot of all config globals (19-22 key-value pairs)
- `apply_app_settings(settings: dict) -> None` – batch update globals + configure_ai_notes()
  - **VESZÉLYES:** 16+ global statement, mutáció közvetlenül az AI config modulban
- `load_schedule_settings()` – Directusból cron + timezone betöltés
- `save_schedule_settings(cron, timezone)` – Directusba mentés
- `load_app_settings()` – Directusból app settings betöltés, meghívja `apply_app_settings()`
- `refresh_app_settings_if_due(max_age_seconds=30, force=False)` – cachelt load

### 1.3. Ollama Resource Status (sorok 303-352)

**Funkciók:**
- `get_ollama_resource_status() -> dict` – HTTP GET `/api/ps` → model list + memory stats
- `current_resource_status() -> dict` – aggregates AI worker status + Ollama + job counts
- `apply_ai_worker_queue_gate(enabled: bool) -> int` – SQL UPDATE: unpause/pause ai jobs

### 1.4. Database Pool Management (sorok 383-403)

**Globális state:**
- `pg_pool: Optional[asyncpg.Pool] = None`

**Funkciók:**
- `get_pg_pool() -> asyncpg.Pool` – lazy init, max_size = FETCH + AI + 2
- `close_pg_pool()` – graceful shutdown

### 1.5. Scheduler (sorok 406-451)

**Globális state:**
- `scheduler: Optional[AsyncIOScheduler] = None`

**Funkciók:**
- `start_refresh_scheduler()` – init AsyncIOScheduler, schedule daily_refresh + cleanup_old_jobs + maybe_enqueue_ai_year_backfill (ha enabled)

### 1.6. Worker State (sorok 116-146)

**Globális mutable state:**
- `worker_task`, `quick_worker_task`, `ai_worker_task` – asyncio.Task references
- `stop_flag`, `stop_fetch_flag`, `stop_quick_flag`, `stop_ai_flag` – control flags
- `current_task_info`, `current_quick_task_info`, `current_ai_task_info` – dicts (in-memory job state)
- `current_job_id`, `current_quick_job_id`, `current_ai_job_id`
- `last_ai_year_backfill_attempt`, `last_runtime_settings_load`, `last_stale_job_reset` – timing floats
- `AI_NOTE_GENERATED_FIELDS` – set of field names to generate
- **ContextVar pool:**
  - `current_job_id_var: ContextVar[Optional[str]]`
  - `current_job_queue_var: ContextVar[Optional[str]]`
  - `current_task_info_var: ContextVar[dict]`

**DirectusClient instance:**
- `directus = DirectusClient(DIRECTUS_URL, DIRECTUS_TOKEN)` – global

### 1.7. Job State Utilities (sorok 456-614)

**Funkciók:**
- `job_dedupe_key(queue, task) -> str` – stable deduplication key (512 char max)
- `update_job_progress(queue, current, total, label)` – update progress in Directus + memory
- `update_current_job_phase(queue, phase, label, extra)` – update phase + extra fields
- `job_status_counts(queue) -> dict` – aggregate counts by status
- `reset_stale_running_jobs_if_due(force) -> int` – debounced call to reset stale (>STALE_JOB_MINUTES)
- `retry_or_fail_job(job, error, stopped)` – bump attempts, requeue or error
- `update_video_ai_status(video_id, status, error)`
- `heartbeat_job(job_id)` – loop every HEARTBEAT_INTERVAL (30s)
- `normalize_claimed_job(row) -> dict` – clean up fetched job row
- `parse_datetime(value) -> Optional[datetime]`
- `job_duration_seconds(job, end) -> Optional[int]`
- `summarize_ai_metrics(metrics) -> str` – format metrics for log/UI
- `claim_next_job(queue, worker_name) -> dict` – SQL: FOR UPDATE SKIP LOCKED + mark running
- `reset_stale_running_jobs(max_age_minutes) -> int` – SQL UPDATE stale running → queued
- `reset_owned_running_jobs(worker_id, queues) -> int` – cleanup after worker restart
- `ensure_database_indexes()` – bootstrap indexes + dedupe cleanup

### 1.8. Worker Loops (sorok 800-1002)

**Handler dictionaries (sorok 795-797):**
- `FETCH_HANDLERS` – { type: callable }
- `QUICK_HANDLERS`
- `AI_HANDLERS`

**Funkciók:**
- `worker_loop(worker_name) -> Coroutine` – main fetch worker
  1. claim_next_job("fetch", ...)
  2. dispatch to FETCH_HANDLERS[task_type]
  3. on success: mark done
  4. on error: retry_or_fail_job
  5. heartbeat task + context vars
  6. **Globális mutáció:** `stop_flag`, `stop_fetch_flag`, `current_task_info`, `current_job_id`

- `ai_worker_loop(worker_name)` – AI notes worker
  - checks `AI_NOTES_WORKER_ENABLED`
  - calls `maybe_enqueue_ai_year_backfill()` on idle
  - **AI job cooldown:** `asyncio.sleep(AI_NOTES_JOB_COOLDOWN_SECONDS)`

- `quick_worker_loop(worker_name)` – quick summaries worker

### 1.9. Channel/Video Processing (sorok 1004-1260)

**Funkciók:**
- `_backfill_metadata(existing, videos)` – update missing date/thumbnail/members-only for existing videos
- `_process_channel_transcripts(transcript_videos, existing, channel_url, channel_id, loop)` – loop over videos, fetch transcript, store
  - **long function (~71 sor)** – mixed concerns: metadata fetch, transcript fetch, progress tracking
  - **executor calls:** fetch_video_info, fetch_transcript_variants

- `process_channel_task(task)` – orchestrate full channel: fetch video list + transcripts
  - **long function (~59 sor)** – coordinator, updates channel status

- `process_single_video_task(task)` – single video URL → create or update video + fetch transcript
  - **long function (~88 sor)** – includes channel auto-create logic

- `process_refresh_task(task)` – refresh one channel

- `process_refresh_dates_task()` – batch update missing dates
  - **long function (~49 sor)**

- `process_refresh_thumbnails_task()` – batch update missing thumbnails
  - **long function (~30 sor)**

### 1.10. AI Notes Processing (sorok 1361-1527)

**Funkciók:**
- `generate_and_store_ai_notes(directus_video_id, video, fields) -> bool` – generate via ai_notes.py + persist
  - progress callback
  - metrics tracking
  - error → ai_notes_status = error
  - **long function (~57 sor)** – handles both full & selective regeneration

- `process_ai_notes_task(task)` – batch: fetch missing, fan out to per-video jobs
  - **long function (~34 sor)**

- `process_single_ai_note_task(task)` – single video AI notes

- `process_quick_note_task(task)` – quick summary → always enqueue full notes after

### 1.11. Job Enqueueing (sorok 1530-1654)

**Funkciók:**
- `enqueue_quick_job(task, label) -> dict`
- `enqueue_ai_note(video_id)` – route: quick or AI based on config
- `_init_handlers()` – populate FETCH_HANDLERS, QUICK_HANDLERS, AI_HANDLERS
- `enqueue_fetch_job(task, label)`
- `enqueue_ai_job(task, label)`
- `maybe_enqueue_ai_year_backfill(source, force) -> dict` – keep AI queue with year backfill
  - **long function (~82 sor)** – throttled, capacity-aware batching

### 1.12. Job Cleanup & Utility (sorok 1657-1740)

**Funkciók:**
- `clear_ai_notes(video_id)` – NULL all AI fields
- `cancel_jobs(queue, predicate, include_running) -> int` – batch cancel
- `cleanup_orphan_ai_pending_videos() -> int` – stale ai_notes_status = pending
- `current_job_snapshot(queue, in_memory, in_memory_job_id) -> dict` – current job status

### 1.13. Worker Control (sorok 1742-1771)

**Funkciók:**
- `restart_ai_worker()` – cancel + recreate ai_worker_task
- `daily_refresh()` – enqueue all channels for refresh (scheduled)
- `cleanup_old_jobs()` – delete old done/cancelled jobs

### 1.14. App Lifecycle (sorok 1773-1862)

**Funkciók:**
- `bootstrap_runtime(cleanup_pending)` – startup sequence
  1. wait for Directus health check
  2. ensure_schema()
  3. ensure_database_indexes()
  4. reset_stale_running_jobs()
  5. load_schedule_settings()
  6. load_app_settings()

- `create_worker_tasks() -> list[asyncio.Task]` – spawn concurrency × worker loop tasks
- `run_worker_service()` – run as standalone service (not in api mode)
- `lifespan(app: FastAPI) -> AsyncContextManager` – FastAPI app lifecycle
  - startup: bootstrap + create worker tasks + start scheduler
  - teardown: cancel workers + shutdown scheduler + close connections

### 1.15. FastAPI Setup (sorok 1865-1881)

- `app = FastAPI(..., lifespan=lifespan)`
- middleware: `require_app_token` – check `x-app-token` header (except /health)
- middleware: `CORSMiddleware`

### 1.16. API Models (sorok 1886-1923)

- `FetchChannelsRequest`, `FetchVideoRequest`, `ScheduleRequest`, `AppSettingsRequest`
- `AiNotesRequest`, `ChannelAiNotesRequest`, `AiNoteRegenerateRequest`, `JobMoveRequest`

### 1.17. UI Constants & Helpers (sorok 1942-1995)

- `UI_PAGE_SIZE = 100`
- `UI_VIDEO_FIELDS` – CSV of fields for UI queries
- `UI_CHANNEL_UPDATE_FIELDS`, `UI_VIDEO_UPDATE_FIELDS` – allowlist
- `directus_query(path, params) -> str` – urlencode helper
- `apply_ui_video_filters(params, search, status, ai, members)`
- `count_ui_videos(extra_params) -> int`

### 1.18. API Endpoints (sorok 2000-2748)

**Health & Status:**
- `GET /health` – queue counts + worker counts
- `GET /status` – detailed status + current tasks + scheduler config
- `GET /resources` – Ollama status snapshot
- `GET /resources/stream` – SSE: continuous Ollama resource monitoring
- `GET /schedule`, `PATCH /schedule` – get/set cron + timezone
- `GET /settings`, `PATCH /settings` – get/update app settings

**Job Management:**
- `GET /jobs` – list jobs (active + completed)
- `POST /jobs/{job_id}/pause`, `/resume`, `/start`
- `POST /jobs/{job_id}/move` – reorder (up/down)
- `DELETE /jobs/{job_id}` – cancel or delete

**UI Endpoints:**
- `GET /ui/channels`, `PATCH /ui/channels/{id}`, `DELETE /ui/channels/{id}`
- `GET /ui/videos` – paginated with filters (search, status, AI, members-only)
- `GET /ui/videos/daily`, `/count`, `/error-videos`
- `GET /ui/channels/{id}/videos`
- `GET /ui/admin-stats`, `/ui/channel-coverage`, `/ui/monthly-video-counts`

**Fetch/Processing:**
- `POST /fetch-channels` – enqueue channel URL list
- `POST /fetch-video` – enqueue single video
- `POST /refresh-channel/{id}` – manual channel refresh
- `POST /refresh-dates`, `/refresh-thumbnails` – batch tasks

**AI Notes:**
- `POST /ai-notes` – batch AI notes from missing videos
- `POST /quick-notes/{video_id}` – priority quick summary
- `POST /ai-notes/{video_id}` – single video AI notes
- `POST /ai-notes/{video_id}/regenerate` – selective field regeneration
- `POST /channels/{id}/ai-notes` – AI notes for all missing in channel
- `DELETE /ai-notes/{video_id}` – clear AI fields + cancel jobs

**Control:**
- `POST /stop`, `/resume` – pause/resume queues globally or per-queue

---

## 2. Felelősségi Körök (Grouped)

### **Config & Environment**
- Lines 59–112: environment parsing, validation, defaults
- Lines 148–301: schedule + app settings loader/saver, dynamic reconfig

### **FastAPI App & Middleware**
- Lines 1865–1881: app init + middleware
- Lines 1997–2748: all API endpoints (18 GET, 16 POST, 2 PATCH, 3 DELETE)

### **Worker Orchestration**
- Lines 116–146: worker state + ContextVar pool
- Lines 795–1002: worker_loop, ai_worker_loop, quick_worker_loop
- Lines 1796–1830: create_worker_tasks, run_worker_service
- Lines 1835–1862: lifespan context manager

### **Job State & Persistence**
- Lines 456–469: job_dedupe_key
- Lines 471–506: update_job_progress, update_current_job_phase
- Lines 508–614: job status utilities (counts, stale reset, claimed, retry logic)
- Lines 1530–1571: enqueue_* functions

### **Channel/Video Fetching**
- Lines 1004–1278: process_channel_task, process_single_video_task, process_refresh_task, refresh dates/thumbnails
- Relies on `youtube_fetcher` for yt-dlp calls + transcript API

### **AI Notes Generation**
- Lines 1361–1527: generate_and_store_ai_notes, process_ai_notes_task, process_single_ai_note_task, process_quick_note_task
- Relies on `ai_notes.py` for ollama/anthropic/openai API calls

### **Job Enqueueing & Backfill**
- Lines 1530–1654: enqueue functions + maybe_enqueue_ai_year_backfill (capacity-aware batching)

### **Scheduler & Maintenance**
- Lines 406–451: start_refresh_scheduler, add daily_refresh + cleanup_old_jobs
- Lines 1754–1771: daily_refresh, cleanup_old_jobs
- Lines 1773–1794: bootstrap_runtime (startup sequence)

### **Database**
- Lines 383–403: asyncpg pool management
- Lines 729–790: ensure_database_indexes (with advisory lock)

### **Utilities**
- Lines 168–179: bool_setting, int_setting
- Lines 1966–1995: Directus query helpers, video filters, counts

### **UI/Admin**
- Lines 1942–1995: UI constants + helpers
- Lines 2000–2184: UI endpoints (channels, videos, stats)

---

## 3. Függőségi Térkép

### **Imports (external & internal)**

```
main.py imports:
├── asyncio, json, logging, os, socket, time (stdlib)
├── datetime, timezone, timedelta, ZoneInfo (stdlib)
├── contextlib.asynccontextmanager, contextvars.ContextVar (stdlib)
├── urllib.parse.urlencode, quote (stdlib)
├── apscheduler.schedulers.asyncio.AsyncIOScheduler
├── fastapi.* (FastAPI, HTTPException, Request, Query, middleware, responses)
├── pydantic.BaseModel
├── asyncpg (PostgreSQL)
├── httpx (HTTP client)
└── Internal modules:
    ├── ai_notes (generate_ai_notes, generate_quick_summary, configure_ai_notes, ...)
    ├── constants (queue names, job types, status codes)
    ├── directus_client (DirectusClient class)
    └── youtube_fetcher (fetch_* functions, parse_*, rate limits)
```

### **Main.py exports (symbols used elsewhere)**

Typically none explicitly exported; module is `__main__` when run as `python main.py`. 
Other modules that may import from main:
- `worker.py` likely imports main's async functions / config
  (not verified; assumed based on docker-compose entry point `["python", "worker.py"]`)

### **Key Calling Patterns**

1. **Worker Loop → Handler:**
   ```
   worker_loop() → claim_next_job() → FETCH_HANDLERS[type](task) → process_*_task()
   ```

2. **Process Task → YouTube Fetcher:**
   ```
   process_channel_task() → loop.run_in_executor(fetch_channel_videos, fetch_transcript_variants, ...)
   ```

3. **Worker → AI Generation:**
   ```
   ai_worker_loop() → process_ai_notes_task() / process_single_ai_note_task()
     → generate_and_store_ai_notes() → generate_ai_notes() [from ai_notes.py]
   ```

4. **API Endpoint → Enqueue → Directus:**
   ```
   POST /fetch-channels → enqueue_fetch_job() → directus.create_job()
   ```

5. **Settings Update → Global Mutation:**
   ```
   PATCH /settings → apply_app_settings() → global assignments + configure_ai_notes()
   ```

6. **Scheduler Trigger:**
   ```
   start_refresh_scheduler() → daily_refresh() [scheduled]
     → enqueue_fetch_job({type: "refresh", ...})
   ```

---

## 4. Code Smells

### **A. Túl hosszú függvények (>30 sor)**

| Függvény | Sorok | Probléma |
|----------|-------|---------|
| `_process_channel_transcripts` | ~71 | Videó loop: metadata fetch, transcript fetch, progress, AI enqueue – mixed concerns |
| `process_channel_task` | ~59 | Coordinator: fetch list, backfill, enqueue transcripts – orchestration overload |
| `process_single_video_task` | ~88 | Channel auto-detection, video creation, transcript fetch – too many branches |
| `process_refresh_dates_task` | ~49 | Batch loop: fetch date metadata, update, counters – could extract loop logic |
| `maybe_enqueue_ai_year_backfill` | ~82 | Complex batching: check enable, throttle, capacity calc, scan + queue – state-heavy |
| `generate_and_store_ai_notes` | ~57 | Error handling, metrics tracking, field filtering, status update – callback + state |
| `process_ai_notes_task` | ~34 | Fan-out loop: fetch missing, skip active, enqueue per-video – mid-length |
| `apply_app_settings` | ~39 | 16+ global assignments; no transaction or rollback |
| `lifespan` | ~28 | Setup + teardown intertwined (bootstrap, workers, scheduler, cleanup) |

### **B. Duplikált kód blokkok**

1. **Worker loop structure (worker_loop, ai_worker_loop, quick_worker_loop):**
   - ~200 sorok 3× ismételt: claim → set context vars → heartbeat → handler dispatch → error retry → context cleanup
   - **Opportunity:** Extract into generic worker factory function

2. **Progress update pattern:**
   - Lines 471–506: `update_job_progress`, `update_current_job_phase` – both manipulate state + call Directus
   - Similar logic in `_process_channel_transcripts` (1048), `process_refresh_dates_task` (1302)

3. **Context var setup:**
   ```python
   job_id_token = current_job_id_var.set(job["id"])
   job_queue_token = current_job_queue_var.set("fetch")
   task_info_token = current_task_info_var.set(...)
   # ... later ...
   current_job_id_var.reset(job_id_token)
   ```
   – Repeated 3× in worker loops

4. **Error handling in batch jobs:**
   - `process_refresh_dates_task`, `maybe_enqueue_ai_year_backfill` – similar loop + skip + enqueue + counter pattern

### **C. Kevert Felelősségek**

1. **`_process_channel_transcripts` (lines 1028–1109):**
   - Concerns: YouTube fetching + DB updates + transcript fetch + AI enqueue + error recovery + progress tracking
   - Ideal split: separate transcript fetcher vs. storage orchestrator

2. **`process_single_video_task` (lines 1172–1259):**
   - Concerns: URL parsing + channel auto-detect + channel creation + video creation + transcript fetch + AI enqueue
   - Lacks separation: should extract channel resolution + video creation into helper

3. **`maybe_enqueue_ai_year_backfill` (lines 1574–1654):**
   - Concerns: throttling logic + capacity management + batch query + deduplication + enqueueing
   - State-heavy: `last_ai_year_backfill_attempt` + multiple config reads

4. **`apply_app_settings` (lines 210–261):**
   - Concerns: global variable mutation + validation + ai_notes module configuration
   - No transaction; if `configure_ai_notes()` fails, globals are half-updated

5. **`worker_loop` (lines 800–862):**
   - Concerns: job claiming + context management + handler dispatch + error classification + heartbeat
   - Ideal: separate context manager + error handler from job loop

### **D. Globális Mutable State**

| Variable | Type | Mutation Points | Risk |
|----------|------|-----------------|------|
| `stop_flag`, `stop_fetch_flag`, etc. | bool | API `/stop`, `/resume` | Race condition if not atomic; workers check but may race on state change |
| `current_job_id`, `current_task_info` | dict/str | worker_loop assign + reset | In-memory; lost on crash; ContextVar provides isolation but globals remain |
| `current_ai_job_id` | str | ai_worker_loop | Similar |
| `last_ai_year_backfill_attempt` | float | maybe_enqueue_ai_year_backfill | Non-atomic read-modify-write |
| `last_runtime_settings_load` | float | load_app_settings | Same |
| `last_stale_job_reset` | float | reset_stale_running_jobs_if_due | Same |
| All AI/Ollama configs (OLLAMA_CHAT_MODEL, etc.) | str/int | apply_app_settings | 16+ assignments; no lock |
| `FETCH_HANDLERS`, `AI_HANDLERS`, etc. | dict | _init_handlers (at import time) | Safe (populated once), but mutable dict |
| `scheduler` | AsyncIOScheduler | start_refresh_scheduler | Single global; can be recreated |
| `pg_pool` | asyncpg.Pool | get_pg_pool | Lazy init; ok if single-threaded async |
| `directus` | DirectusClient | Global init | Reused httpx.AsyncClient (line 63–65); thread-safe? |

### **E. Magic Numbers / String Literals**

| Value | Usage | Risk |
|-------|-------|------|
| `45`, `75` | TRANSCRIPT_DELAY_MIN/MAX (youtube_fetcher) | Rate limit: YouTube might change; hardcoded |
| `5`, `15` | CHANNEL_LIST_DELAY_MIN/MAX | Rate limit: same |
| `3000` | QUICK_MAX_CHARS (ai_notes.py line 161) | Arbitrary; no rationale in comment |
| `512` | dedupe_key max length (line 468) | No clear rationale |
| `30`, `60`, `300`, `600` | Various timeouts (HEARTBEAT_INTERVAL, OLLAMA_TIMEOUT) | Scattered; no centralized timeout config |
| `50` | AI_NOTES_YEAR_BACKFILL_BATCH_LIMIT default | No rationale |
| `"0 7 * * *"` | REFRESH_CRON default | Time 7 AM hardcoded; no flexibility comment |
| `100` (UI_PAGE_SIZE) | Pagination | Arbitrary |
| `1000` | Summary field truncation (error_message[:1000]) | Multiple places; inconsistent |
| `8192` | max_tokens in Anthropic payload (ai_notes.py:400) | No rationale |

### **F. Mélyen Egymásba Ágyazott Logika (>3 szint)**

1. **`_process_channel_transcripts` (lines 1038–1099):**
   ```
   for video in transcript_videos:  // 1
       try:                          // 2
           if not uploaded_at:       // 3
               for fmt_args in ...: // 4
                   if result:       // 5
   ```
   – 5 nesting level in metadata fetch

2. **`process_single_video_task` (lines 1202–1225):**
   ```
   if not channel_id:                    // 1
       if yt_channel_url or ...:        // 2
           if existing_ch:               // 3
               ...
           else:                        // 3
               if not existing_ch and ...: // 4
   ```
   – 4 levels; complex branch tree

3. **`apply_ui_video_filters` (lines 1970–1986):**
   ```
   if search:
       params[...] = ...
   if status_filter:                     // 1
       ...
   if ai_filter == "done":               // 1
       ...
   elif ai_filter == "missing":          // 1
       if year:                          // 2 (inside another function)
   ```
   – Chain of if-elif is readable, but nesting varies

### **G. Rejtett Mellékhatások**

1. **`apply_app_settings()` (lines 210–261):**
   - Modifies 16+ global variables silently
   - Calls `configure_ai_notes()` which modifies ai_notes.py globals
   - No return value; caller must know side effect occurred

2. **`start_refresh_scheduler()` (lines 406–451):**
   - Shuts down previous scheduler if exists
   - Re-initializes; can cause missed triggers if called during a trigger
   - `logger.info` but silent to API caller

3. **`load_app_settings()` (lines 283–295):**
   - Calls `apply_app_settings()` → 16+ global mutations
   - Sets `last_runtime_settings_load` (timing side effect)
   - Swallows exceptions silently (only logs warning)

4. **`worker_loop()` (lines 800–862):**
   - Modifies `current_job_id`, `current_task_info` (globals)
   - ContextVar isolation helps, but still leaks state
   - Calls `heartbeat_job()` which spawns background task

5. **`maybe_enqueue_ai_year_backfill()` (lines 1574–1654):**
   - Modifies `last_ai_year_backfill_attempt` (non-atomic)
   - Queries Directus (I/O side effect)
   - Enqueues jobs
   - Returns statistics but also mutates global

6. **`claim_next_job()` (lines 635–672):**
   - SQL transaction: FOR UPDATE + UPDATE (atomic in DB, but multi-step)
   - Mutates job state to `running`

---

## 5. Kockázati Területek

### **A. Shared Mutable State & Race Conditions**

**Risk 1: Stop Flags**
- Lines 120–123: `stop_flag`, `stop_fetch_flag`, `stop_ai_flag` are simple bools
- Modified by API `/stop` endpoint (lines 2698–2725)
- Read by worker loops (lines 804, 869, 942, etc.)
- **Issue:** No locking; if scheduler or API thread sets flag while worker reads, unpredictable behavior
- **Severity:** MEDIUM – workers check debounced (WORKER_POLL_BACKOFF = 2s), so race window is small

**Risk 2: Current Job Info Globals**
- Lines 124–129: `current_task_info`, `current_job_id` (and quick/ai variants)
- Modified by worker loop assignments (e.g., line 825, 826)
- Read by status endpoints (lines 2209, 2211)
- **Issue:** No atomic update; status endpoint might read partial state
- **Mitigation:** ContextVar usage helps isolation; in-memory snapshot is stale-but-safe
- **Severity:** LOW – status is informational; stale data is acceptable

**Risk 3: Last-* Timing Floats**
- Lines 134–136: `last_ai_year_backfill_attempt`, `last_runtime_settings_load`, `last_stale_job_reset`
- Non-atomic read-modify-write pattern: `if now - last > threshold: last = now`
- **Issue:** Two workers reading the same float, both deciding to execute, both updating
- **Scenario:** Two `maybe_enqueue_ai_year_backfill()` calls race → both enqueue
- **Severity:** MEDIUM – duplicates are deduplicated by `dedupe_key`, but wastes queries

**Risk 4: Global Config Variables (OLLAMA_CHAT_MODEL, etc.)**
- Lines 66–111: 16+ global settings
- Modified atomically in `apply_app_settings()` but read non-atomically across app
- **Issue:** Mid-update, a thread reads old OLLAMA_CHAT_MODEL but new OLLAMA_TIMEOUT
- **Scenario:** Settings API patches; worker mid-request gets inconsistent tuple
- **Severity:** MEDIUM – unlikely in practice (settings rarely change), but possible

### **B. Worker Interaction & Async Cancellation**

**Risk 1: Heartbeat Task Lifecycle**
- Lines 830, 901, 969: `heartbeat_task = asyncio.create_task(heartbeat_job(...))`
- Line 853–856: Cleanup tries to cancel but swallows CancelledError
- **Issue:** If heartbeat raises non-CancelledError, task leaks / crashes silently
- **Severity:** LOW – heartbeat only updates Directus, failure is non-critical

**Risk 2: Worker Restart on AI Settings Change**
- Lines 1742–1751: `restart_ai_worker()` cancels + awaits + recreates
- Called from `/ai-notes/{id}` endpoint during concurrent jobs
- **Issue:** If cancel hangs, endpoint hangs; no timeout on await
- **Severity:** MEDIUM – endpoint could timeout; manual restart required

**Risk 3: Stale Job Reset Race**
- Lines 517–526: `reset_stale_running_jobs_if_due()` debounced (60s min)
- Worker calls this before claiming (line 808)
- **Issue:** If two workers claim simultaneously, both might mark the same job running
- **Mitigation:** SQL FOR UPDATE SKIP LOCKED should serialize; but if claim fails mid-transaction, orphans possible
- **Severity:** LOW – database locks help; edge case

**Risk 4: Worker Async Gather in Shutdown**
- Lines 1825–1829: `asyncio.gather(*tasks, return_exceptions=True)` after cancel
- If a task is hung (e.g., waiting for Directus), gather hangs forever
- **Severity:** MEDIUM – no timeout on gather; app shutdown hangs

### **C. Startup & Bootstrap Timing**

**Risk 1: Schema Bootstrap Ordering**
- Lines 1773–1794: `bootstrap_runtime()` is called in `lifespan()` startup
- Waits for Directus health (40 × 3s = 120s max), but if Postgres is down, Directus can't start
- **Issue:** FastAPI starts listener before bootstrap completes; requests fail before schema exists
- **Mitigation:** docker-compose depends_on + healthcheck help
- **Severity:** MEDIUM – race window if services start out of order

**Risk 2: Settings Load During Startup**
- Lines 1792–1793: `load_schedule_settings()`, `load_app_settings()` called in bootstrap
- If Directus is slow, app startup blocks
- **Severity:** LOW – startup delay acceptable

**Risk 3: Scheduler Timezone Resolution**
- Lines 148–153: `get_scheduler_timezone()` catches ZoneInfoNotFoundError and falls back to UTC
- If SCHEDULER_TIMEZONE is invalid, silently uses UTC with no notification
- **Severity:** LOW – silent fallback is safe but confusing

### **D. Database Constraints & Concurrency**

**Risk 1: Dedupe Index Uniqueness**
- Lines 740: `CREATE UNIQUE INDEX ... WHERE status IN ('queued', 'running', 'paused')`
- If two jobs with same dedupe_key both try to insert while one is transitioning done→queued, conflict
- **Scenario:** Job A finishes + marked done (not in index), Job B tries to insert with same key
- **Mitigation:** `DirectusClient.create_job()` uses dedupe_key lookup + dedupe check (lines 290–313)
- **Severity:** MEDIUM – race window small but possible

**Risk 2: Stale Job Cleanup Advisory Lock**
- Lines 754–790: Advisory lock to serialize dedupe cleanup
- If two services start, both acquire lock sequentially; no concurrent dedupe cleanup
- **Severity:** LOW – serialization is intentional

**Risk 3: Video AI Status Orphans**
- Lines 1696–1711: `cleanup_orphan_ai_pending_videos()` clears stale `ai_notes_status = pending` without active jobs
- If job transitions quickly, video status might be cleared before job starts
- **Scenario:** Job enqueued + video marked pending; service crashes; orphan video marked pending forever
- **Mitigation:** cleanup called on startup; helps but not perfect
- **Severity:** MEDIUM – UI shows stuck pending video; manual cleanup needed

### **E. External Service Dependencies**

**Risk 1: Ollama Streaming Timeout**
- Lines 277–335 (ai_notes.py): `httpx.wait_for(_stream(), timeout=OLLAMA_TIMEOUT)`
- If Ollama hangs mid-stream, timeout triggers → TimeoutError
- Worker marks job as error; Directus updated
- **Issue:** No retry for timeout; user must manually retry
- **Severity:** HIGH – AI job lost; requires manual intervention

**Risk 2: YouTube API Rate Limiting**
- Lines 45–75 (youtube_fetcher.py): Hard-coded TRANSCRIPT_DELAY_MIN/MAX
- If YouTube detection changes, delays might be insufficient
- **Severity:** MEDIUM – YouTube would block; workers would hang or fail

**Risk 3: Directus Connection Pool Leak**
- Lines 387–395: `asyncpg.create_pool(..., max_size=max(4, FETCH + AI + 2))`
- If worker holds connection longer than expected, pool exhausted
- **Issue:** No connection timeout; can hang indefinitely
- **Severity:** MEDIUM – if Postgres is slow, all workers stall

### **F. Settings & Configuration**

**Risk 1: Settings Hot-Reload Inconsistency**
- Lines 298–300: `refresh_app_settings_if_due()` reloads every 30s if forced
- AI worker calls this (line 893), but timing is unpredictable
- **Issue:** Two workers see different configs if reload happens mid-request
- **Severity:** LOW – settings rarely change; delay acceptable

**Risk 2: Dynamic Handler Registration**
- Lines 1545–1561: `_init_handlers()` called at module import time
- If new handler needed, requires code change + restart
- **Severity:** LOW – by design; extensibility not a goal

**Risk 3: OLLAMA_BASE_URL / API Key Mutation**
- Lines 220, 244, 248: Direct string assignment to globals
- If multiple workers call simultaneously, race on string assignment (safe in Python due to GIL, but order unpredictable)
- **Severity:** LOW – Python GIL provides de facto locking; unlikely to corrupt

### **G. Long-Running Operations**

**Risk 1: Transcript Fetch Loop (Long Video Lists)**
- Lines 1038–1109: Loop over 100s of videos, each fetch ~60s
- Worker is blocked; cannot process other tasks
- **Issue:** Single worker processes one channel = hours
- **Mitigation:** FETCH_WORKER_CONCURRENCY allows parallel workers
- **Severity:** LOW – by design; concurrency handles it

**Risk 2: Batch AI Notes Enqueue (Year Backfill)**
- Lines 1614–1635: Fetch 100s of videos, enqueue 1 per loop iteration
- Loop can take minutes; worker cannot yield
- **Severity:** LOW – intentional; capacity-aware batching limits batch size

**Risk 3: Metadata Backfill in Channel Process**
- Lines 1004–1025: Loop updates every existing video metadata
- If 10k videos, 10k Directus PATCH calls sequentially
- **Mitigation:** Concurrent workers help, but one worker = serial
- **Severity:** MEDIUM – performance issue; should batch updates

### **H. Error Handling & Recovery**

**Risk 1: Transcript Fetch Fallback Chain**
- Lines 341–390 (youtube_fetcher.py): Primary → fallback → fallback → None
- If all fail, returns (None, None) silently
- Video marked `status = no_transcript`; no error logging at call site
- **Severity:** LOW – correct behavior; video just has no transcript

**Risk 2: Silent Exception Swallowing**
- Lines 274–275, 294–295: catch Exception, log warning, continue
- Errors in app settings load → app starts with stale config
- **Severity:** MEDIUM – misconfiguration not surfaced to user

**Risk 3: Retry Logic Limitations**
- Lines 529–557: `retry_or_fail_job()` retries up to max_attempts times
- If max_attempts=3, task fails forever if always fails
- **Severity:** MEDIUM – no exponential backoff; immediate retry hammers service

**Risk 4: Cancelled Job Status Confusion**
- Lines 837–845: Worker checks `latest.get("status") != "cancelled"` before marking done
- If user cancels mid-processing, job orphaned as running
- **Mitigation:** Periodic stale reset (every 30+ min) helps
- **Severity:** MEDIUM – manual cleanup needed until reset runs

### **I. Refactoring Risks**

**High-Risk Areas for Refactor:**

1. **Worker Loop Extraction (lines 800–862, 865–935, 938–1001)**
   - Risk: Context var setup + heartbeat + error handling deeply coupled
   - Refactor: Extract to generic worker factory → must maintain identical error semantics
   - **Refactor Difficulty:** HIGH

2. **Settings Mutation (apply_app_settings lines 210–261)**
   - Risk: 16+ global assignments; if one fails, partially applied
   - Refactor: Transaction-like pattern (collect, validate, apply atomically)
   - **Difficulty:** MEDIUM – need lock or atomic dict swap

3. **Job Enqueueing Pipeline (enqueue_ai_note lines 1535–1542)**
   - Risk: Routes to quick or AI based on runtime config; logic scattered
   - Refactor: Job type dispatch table
   - **Difficulty:** LOW – straightforward

4. **Long Functions (process_channel_task, _process_channel_transcripts)**
   - Risk: Multiple responsibilities; hard to test
   - Refactor: Split into fetcher + storage layers
   - **Difficulty:** MEDIUM – requires interface definition

5. **Context Var Boilerplate (3× in worker loops)**
   - Risk: Duplicate cleanup logic; easy to forget reset
   - Refactor: Context manager decorator
   - **Difficulty:** LOW

---

## 6. Javaslatok Csökkentésre

1. **Introduce Worker Base Class**
   - Consolidate worker_loop, ai_worker_loop, quick_worker_loop into single factory
   - Reduces 200-line duplication

2. **Settings Transaction**
   - Wrap apply_app_settings in try-except with rollback capability
   - Atomic dictionary swap

3. **Extract Long Functions**
   - Split process_channel_task → (fetch_video_list, store_transcripts)
   - Split process_single_video_task → (resolve_channel, create_video, fetch_transcript)

4. **Centralize Timing Constants**
   - Move HEARTBEAT_INTERVAL, WORKER_IDLE_SLEEP, etc. to constants.py with rationale

5. **Add Timeouts to Async Operations**
   - `asyncio.wait_for(gather(...), timeout=30)` in lifespan shutdown
   - Prevents app hang on stuck workers

6. **Implement Settings Lock**
   - Use asyncio.Lock for global config reads/writes
   - Ensures consistency across workers

7. **Batch Video Updates**
   - Instead of loop + individual PATCH, batch updates to Directus
   - Reduces query count in _backfill_metadata, cleanup_orphan_ai_pending_videos

8. **Explicit Retry Policy**
   - Exponential backoff or jitter in retry_or_fail_job
   - Prevents retry storms

9. **Structured Logging**
   - Add correlation IDs to job processing for tracing
   - Easier debugging of concurrent issues

10. **E2E Test for Worker Restart**
    - Test that stop_flag → cancel → restart maintains consistency
    - Validates refactored worker pattern

---

## 7. Összefoglalás

**Erősségek:**
- Clear handler dispatch pattern (FETCH_HANDLERS, AI_HANDLERS)
- Good use of asyncio.Task + context managers for lifecycle
- Comprehensive health/status endpoints for monitoring
- ContextVar helps worker isolation

**Gyengeségek:**
- Heavy reliance on global mutable state (16+ globals)
- Long functions with mixed concerns
- Race conditions on timing floats + config updates
- No locking for concurrent access
- Silent exception swallowing in critical paths

**Refactor Priority:**
1. Worker loop consolidation (HIGH impact, MEDIUM difficulty)
2. Settings transaction + lock (MEDIUM impact, LOW difficulty)
3. Extract long functions (MEDIUM impact, MEDIUM difficulty)
4. Add shutdown timeout (HIGH impact, LOW difficulty)
5. Batch DB updates (LOW impact, LOW difficulty)

**Biggest Risks:**
1. Stale job cleanup can deadlock if hung (no timeout on gather)
2. Race on dedupe_key during status transitions
3. Ollama timeout loses job without retry
4. Settings reload not atomic across workers
5. Video AI status orphans accumulate if service crashes

---

## Appendix: Entry Points

**docker-compose.yml line 66:** `FETCHER_ROLE: api`
- Starts FastAPI app + scheduler, no workers in-process

**docker-compose.yml line 79:** `command: ["python", "worker.py"]`
- Worker role; runs `run_worker_service()` (assumed; worker.py not analyzed here)

---

*Analysis completed: 2748 lines of main.py, 619 lines of directus_client.py, 486 lines of youtube_fetcher.py, 701 lines of ai_notes.py*
