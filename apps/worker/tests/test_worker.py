from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, call, patch

from arq import Retry

from travelmind_api.jobs.handlers import JobRetryRequested
from travelmind_worker import worker


async def _pending_heartbeat(_job_id: str) -> None:
    await asyncio.Event().wait()


class WorkerExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_recovers_and_requeues_stale_jobs(self) -> None:
        redis = AsyncMock()
        with (
            patch.object(worker, "init_db") as init_db,
            patch.object(worker, "recover_stale_jobs", return_value=["job-a", "job-b"]) as recover,
        ):
            await worker.startup({"redis": redis})

        init_db.assert_called_once_with()
        recover.assert_called_once_with(
            stale_after_seconds=worker.settings.job_stale_after_seconds,
        )
        self.assertEqual(
            redis.enqueue_job.await_args_list,
            [
                call("process_job", job_id="job-a", _job_id="travelmind:job-a"),
                call("process_job", job_id="job-b", _job_id="travelmind:job-b"),
            ],
        )

    async def test_process_job_runs_handler_and_cleans_up_heartbeat(self) -> None:
        with (
            patch.object(worker, "_heartbeat_loop", side_effect=_pending_heartbeat) as heartbeat,
            patch.object(worker, "run_job_handler") as run_job_handler,
        ):
            await worker.process_job({}, "job-a")

        heartbeat.assert_awaited_once_with("job-a")
        run_job_handler.assert_called_once_with("job-a", retry_transient=True)

    async def test_process_job_maps_retry_request_to_arq_retry(self) -> None:
        with (
            patch.object(worker, "_heartbeat_loop", side_effect=_pending_heartbeat),
            patch.object(worker, "run_job_handler", side_effect=JobRetryRequested(7)),
        ):
            with self.assertRaises(Retry) as raised:
                await worker.process_job({}, "job-retry")

        self.assertEqual(raised.exception.defer_score, 7000)

    async def test_heartbeat_stops_when_job_is_no_longer_active(self) -> None:
        with (
            patch.object(worker.asyncio, "sleep", new=AsyncMock()) as sleep,
            patch.object(worker, "touch_job_heartbeat", return_value=False) as touch,
        ):
            await worker._heartbeat_loop("job-finished")

        sleep.assert_awaited_once_with(max(worker.settings.job_heartbeat_seconds, 1))
        touch.assert_called_once_with("job-finished")


if __name__ == "__main__":
    unittest.main()
