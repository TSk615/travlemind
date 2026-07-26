from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from arq import Retry, run_worker
from arq.connections import RedisSettings

from travelmind_api.core.config import get_settings
from travelmind_api.core.database import init_db
from travelmind_api.jobs.handlers import JobRetryRequested, process_job as run_job_handler
from travelmind_api.services.job_service import recover_stale_jobs, touch_job_heartbeat


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
    await asyncio.to_thread(init_db)
    recovered_job_ids = await asyncio.to_thread(
        recover_stale_jobs,
        stale_after_seconds=settings.job_stale_after_seconds,
    )
    redis = ctx.get("redis")
    if redis is not None:
        for job_id in recovered_job_ids:
            await redis.enqueue_job("process_job", job_id=job_id, _job_id=f"travelmind:{job_id}")


async def _heartbeat_loop(job_id: str) -> None:
    interval = max(settings.job_heartbeat_seconds, 1)
    while True:
        await asyncio.sleep(interval)
        active = await asyncio.to_thread(touch_job_heartbeat, job_id)
        if not active:
            return


async def process_job(ctx, job_id: str) -> None:
    del ctx
    heartbeat_task = asyncio.create_task(_heartbeat_loop(job_id))
    try:
        await asyncio.to_thread(run_job_handler, job_id, retry_transient=True)
    except JobRetryRequested as exc:
        raise Retry(defer=exc.delay_seconds) from exc
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


class WorkerSettings:
    functions = [process_job]
    redis_settings = redis_settings_from_url(settings.redis_url)
    on_startup = startup
    max_jobs = settings.worker_max_jobs
    max_tries = settings.job_max_attempts
    job_timeout = settings.job_timeout_seconds
    keep_result = settings.job_result_ttl_seconds
    health_check_interval = max(settings.job_heartbeat_seconds, 5)


if __name__ == "__main__":
    run_worker(WorkerSettings)
