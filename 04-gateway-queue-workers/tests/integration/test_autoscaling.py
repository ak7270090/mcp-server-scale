import time

import anyio
import pytest

from tests.integration.stack_control import (
    StackConfig,
    apply_stack_config,
    list_running_worker_ids,
    write_result_section,
)
from tests.integration.test_queue_behaviour import run_concurrent_slow_jobs

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

MAX_WORKERS = 10
BURST_JOB_COUNT = 30
BURST_JOB_SECONDS = 4
SAMPLE_INTERVAL_SECONDS = 1.0
SCALE_DOWN_WAIT_SECONDS = 60


class WorkerCountSampler:
    def __init__(self) -> None:
        self.samples: list[tuple[float, int]] = []
        self._started_at = time.monotonic()

    async def sample_until_cancelled(self) -> None:
        while True:
            await self.sample_once()
            await anyio.sleep(SAMPLE_INTERVAL_SECONDS)

    async def sample_once(self) -> int:
        running_workers = len(await anyio.to_thread.run_sync(list_running_worker_ids))
        self.samples.append((round(time.monotonic() - self._started_at, 1), running_workers))
        return running_workers

    async def wait_for_worker_count(self, worker_count: int, timeout_seconds: float) -> None:
        """Poll Docker (state no event can tell us about) until the count matches."""
        for _ in range(int(timeout_seconds / SAMPLE_INTERVAL_SECONDS)):
            if await self.sample_once() == worker_count:
                return
            await anyio.sleep(SAMPLE_INTERVAL_SECONDS)
        raise TimeoutError(f"worker count never reached {worker_count}: {self.samples[-5:]}")


async def test_autoscaler_follows_queue_depth() -> None:
    apply_stack_config(
        StackConfig(worker_count=MAX_WORKERS, is_autoscaled=True, max_workers=MAX_WORKERS)
    )
    sampler = WorkerCountSampler()
    await sampler.wait_for_worker_count(1, timeout_seconds=SCALE_DOWN_WAIT_SECONDS)
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(sampler.sample_until_cancelled)
        outcomes = await run_concurrent_slow_jobs(BURST_JOB_COUNT, BURST_JOB_SECONDS)
        task_group.cancel_scope.cancel()
    peak_workers = max(workers for _, workers in sampler.samples)
    await sampler.wait_for_worker_count(1, timeout_seconds=SCALE_DOWN_WAIT_SECONDS)
    timeline = "\n".join(f"| {second} | {workers} |" for second, workers in sampler.samples)
    write_result_section(
        "autoscaling.md",
        f"Autoscaler: {BURST_JOB_COUNT} x run_slow_job({BURST_JOB_SECONDS}), "
        f"min 1, max {MAX_WORKERS}",
        f"Succeeded: {outcomes.succeeded_count}/{BURST_JOB_COUNT}, peak workers: {peak_workers}\n\n"
        f"| Seconds | Running workers |\n|---|---|\n{timeline}",
    )

    assert outcomes.succeeded_count == BURST_JOB_COUNT
    assert peak_workers >= MAX_WORKERS // 2
