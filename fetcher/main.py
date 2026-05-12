"""YouTube Transcript Fetcher — FastAPI composition root."""

import asyncio
import logging
from contextlib import asynccontextmanager

import scheduler as scheduler_module
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import worker_state
from db import close_pg_pool
from routes.ai import router as ai_router
from routes.fetch import router as fetch_router
from routes.jobs import router as jobs_router
from routes.status import router as status_router
from routes.ui import router as ui_router
from scheduler import start_refresh_scheduler
from worker_state import directus
from workers import bootstrap_runtime, create_worker_tasks, run_worker_service  # noqa: F401 run_worker_service used by worker.py

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bootstrap_runtime(cleanup_pending=config.FETCHER_ROLE in {"api", "all"})

    worker_tasks = []
    if config.FETCHER_ROLE in {"all", "worker"}:
        worker_tasks = create_worker_tasks()
        worker_state.worker_task = next((task for task in worker_tasks if "fetch" in task.get_name()), None)
        worker_state.ai_worker_task = next((task for task in worker_tasks if "ai" in task.get_name()), None)

    if config.FETCHER_ROLE in {"api", "all"}:
        start_refresh_scheduler()
    else:
        logger.info(f"Fetcher API started in role={config.FETCHER_ROLE}; scheduler disabled")

    yield

    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    if scheduler_module.scheduler:
        scheduler_module.scheduler.shutdown(wait=False)
    await close_pg_pool()
    await directus.close()


app = FastAPI(title="YouTube Transcript Fetcher", lifespan=lifespan)


@app.middleware("http")
async def require_app_token(request: Request, call_next):
    if config.APP_API_TOKEN and request.url.path not in {"/health"}:
        if request.headers.get("x-app-token") != config.APP_API_TOKEN:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=config.APP_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status_router)
app.include_router(jobs_router)
app.include_router(ui_router)
app.include_router(fetch_router)
app.include_router(ai_router)
