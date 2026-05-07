"""Worker-only entrypoint for processing persisted fetcher jobs."""

import asyncio
import logging

from main import run_worker_service


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


if __name__ == "__main__":
    asyncio.run(run_worker_service())
