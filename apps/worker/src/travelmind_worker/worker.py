from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

from arq import run_worker
from arq.connections import RedisSettings

ROOT = Path(__file__).resolve().parents[4]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    # Reuse the API package directly until we split shared backend code into a
    # dedicated Python package. This keeps the worker aligned with API models.
    sys.path.insert(0, str(API_SRC))

from travelmind_api.core.config import get_settings  # noqa: E402
from travelmind_api.core.database import init_db  # noqa: E402
from travelmind_api.jobs.handlers import process_job as run_job_handler  # noqa: E402


settings = get_settings()


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or 0),
        password=parsed.password,
    )


async def startup(ctx) -> None:
    del ctx
    await asyncio.to_thread(init_db)


async def process_job(ctx, job_id: str) -> None:
    del ctx
    await asyncio.to_thread(run_job_handler, job_id)


class WorkerSettings:
    functions = [process_job]
    redis_settings = redis_settings_from_url(settings.redis_url)
    on_startup = startup


if __name__ == "__main__":
    run_worker(WorkerSettings)
