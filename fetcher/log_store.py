"""Batches log records to Postgres so fetcher/fetch-worker/ai-worker logs are all visible from one place (see routes/status.py::get_logs)."""

import asyncio
import logging
from datetime import datetime, timezone

import config
from db import get_pg_pool

FLUSH_INTERVAL_SECONDS = 3


class PostgresLogHandler(logging.Handler):
    def __init__(self, source: str):
        super().__init__()
        self.source = source
        self._buffer: list[tuple] = []

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append((
            datetime.now(timezone.utc), self.source, record.levelname, record.name, self.format(record),
        ))

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            if not self._buffer:
                continue
            batch, self._buffer = self._buffer, []
            try:
                pool = await get_pg_pool()
                await pool.executemany(
                    "INSERT INTO app_logs (ts, source, level, logger, message) VALUES ($1, $2, $3, $4, $5)",
                    batch,
                )
            except Exception:
                pass  # best-effort; log persistence must never crash the app


def install_log_handler() -> None:
    source = config.WORKER_ID if config.FETCHER_ROLE == "worker" else "api"
    handler = PostgresLogHandler(source)
    logging.getLogger().addHandler(handler)
    asyncio.create_task(handler.flush_loop())


async def cleanup_old_logs() -> None:
    pool = await get_pg_pool()
    await pool.execute(
        "DELETE FROM app_logs WHERE ts < now() - make_interval(days => $1)",
        config.LOG_RETENTION_DAYS,
    )
