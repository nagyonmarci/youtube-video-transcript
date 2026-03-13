from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import channels, videos, auth
from app.worker import worker_loop
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start worker on startup
    worker_task = asyncio.create_task(worker_loop())
    yield
    # Cleanup on shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="YouTube Transcript API",
    version="1.0.0",
    redirect_slashes=False,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4321"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(channels.router)
app.include_router(videos.router)

@app.get("/health")
async def health():
    return {"status": "ok"}
