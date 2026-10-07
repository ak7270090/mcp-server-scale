import time

import anyio
import pytest
from mcp import ClientSession, types

from tests.integration.mcp_client import ProgressLog, WorkerLog, open_gateway_session
from tests.integration.stack_control import (
    StackConfig,
    apply_stack_config,
    kill_worker,
    start_worker,
    write_result_section,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

THROUGHPUT_JOB_COUNT = 10
THROUGHPUT_JOB_SECONDS = 2
THROUGHPUT_WORKER_COUNTS = (1, 5, 10)
REDELIVERY_JOB_SECONDS = 6
CANCELLED_JOB_SECONDS = 30
MAX_SECONDS_FOR_CALL_AFTER_CANCEL = 5
SMALL_QUEUE_SIZE = 3
BURST_CALL_COUNT = 10


class CallOutcomes:
    def __init__(self) -> None:
        self.results: list[types.CallToolResult] = []

    async def call_slow_job(self, seconds: int) -> None:
        async with open_gateway_session() as session:
            self.results.append(await session.call_tool("run_slow_job", {"seconds": seconds}))

    @property
    def rejected_count(self) -> int:
        return sum(
            "queue is full" in result.content[0].text for result in self.results if result.isError
        )

    @property
    def succeeded_count(self) -> int:
        return sum(not result.isError for result in self.results)


class FirstProgressWatcher:
    """Message handler that remembers the progress token (the request ID) of the first progress."""

    def __init__(self) -> None:
        self.progress_token: str | int | None = None
        self.has_progress = anyio.Event()

    async def handle(self, message: object) -> None:
        if isinstance(message, types.ServerNotification) and isinstance(
            message.root, types.ProgressNotification
        ):
            self.progress_token = message.root.params.progressToken
            self.has_progress.set()


async def run_concurrent_slow_jobs(job_count: int, seconds: int) -> CallOutcomes:
    outcomes = CallOutcomes()
    async with anyio.create_task_group() as task_group:
        for _ in range(job_count):
            task_group.start_soon(outcomes.call_slow_job, seconds)
    return outcomes


async def call_slow_job_until_cancelled(session: ClientSession, progress_log: ProgressLog) -> None:
    await session.call_tool(
        "run_slow_job", {"seconds": CANCELLED_JOB_SECONDS}, progress_callback=progress_log.record
    )


async def test_throughput_rises_with_worker_count() -> None:
    seconds_by_worker_count = {}
    for worker_count in THROUGHPUT_WORKER_COUNTS:
        apply_stack_config(StackConfig(worker_count=worker_count))
        started_at = time.monotonic()
        outcomes = await run_concurrent_slow_jobs(THROUGHPUT_JOB_COUNT, THROUGHPUT_JOB_SECONDS)
        seconds_by_worker_count[worker_count] = round(time.monotonic() - started_at, 1)
        assert outcomes.succeeded_count == THROUGHPUT_JOB_COUNT
    total_job_seconds = THROUGHPUT_JOB_COUNT * THROUGHPUT_JOB_SECONDS
    rows = "\n".join(
        f"| {workers} | {seconds} s | {total_job_seconds / seconds:.2f} |"
        for workers, seconds in seconds_by_worker_count.items()
    )
    write_result_section(
        "throughput.md",
        f"{THROUGHPUT_JOB_COUNT} concurrent run_slow_job({THROUGHPUT_JOB_SECONDS}) calls",
        f"| Workers | Wall time | Job-seconds per second |\n|---|---|---|\n{rows}",
    )

    assert seconds_by_worker_count[10] < seconds_by_worker_count[1] / 3


async def test_killed_worker_job_is_redelivered_and_completes_once() -> None:
    apply_stack_config(StackConfig(worker_count=2))
    worker_log = WorkerLog()
    progress_log = ProgressLog(target_count=2)
    outcome = CallOutcomes()
    async with (
        open_gateway_session(logging_callback=worker_log.record) as session,
        anyio.create_task_group() as task_group,
    ):
        task_group.start_soon(record_slow_job_result, session, progress_log, outcome)
        with anyio.fail_after(30):
            await progress_log.has_reached_target.wait()
        killed_worker = worker_log.latest_worker
        await anyio.to_thread.run_sync(kill_worker, killed_worker)
    await anyio.to_thread.run_sync(start_worker, killed_worker)
    write_result_section(
        "redelivery.md",
        "Worker killed during run_slow_job(6)",
        f"Attempts (attempt, worker): {worker_log.attempts}\n\n"
        f"Progress seen by the client: {progress_log.progress_values}\n\n"
        f"Result: {outcome.results[0].structuredContent}",
    )

    assert not outcome.results[0].isError
    assert [attempt for attempt, _ in worker_log.attempts] == [1, 2]
    assert worker_log.attempts[1][1] != killed_worker
    assert progress_log.progress_values == [
        float(step) for step in range(1, REDELIVERY_JOB_SECONDS + 1)
    ]


async def record_slow_job_result(
    session: ClientSession, progress_log: ProgressLog, outcome: CallOutcomes
) -> None:
    outcome.results.append(
        await session.call_tool(
            "run_slow_job",
            {"seconds": REDELIVERY_JOB_SECONDS},
            progress_callback=progress_log.record,
        )
    )


async def test_cancelled_job_frees_the_only_worker() -> None:
    apply_stack_config(StackConfig(worker_count=1))
    watcher = FirstProgressWatcher()
    async with open_gateway_session(message_handler=watcher.handle) as session:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(call_slow_job_until_cancelled, session, ProgressLog())
            with anyio.fail_after(30):
                await watcher.has_progress.wait()
            await session.send_notification(
                types.ClientNotification(
                    types.CancelledNotification(
                        params=types.CancelledNotificationParams(
                            requestId=watcher.progress_token, reason="integration test"
                        )
                    )
                )
            )
            task_group.cancel_scope.cancel()
        started_at = time.monotonic()
        await session.call_tool("get_replica_id")
        seconds_for_next_call = time.monotonic() - started_at
    write_result_section(
        "cancellation.md",
        f"Cancel run_slow_job({CANCELLED_JOB_SECONDS}) after the first progress, 1 worker",
        f"Next call on the same worker answered in {seconds_for_next_call:.2f} s",
    )

    assert seconds_for_next_call < MAX_SECONDS_FOR_CALL_AFTER_CANCEL


async def test_full_queue_rejects_calls_cleanly() -> None:
    apply_stack_config(StackConfig(worker_count=1, queue_max_pending=SMALL_QUEUE_SIZE))
    outcomes = await run_concurrent_slow_jobs(BURST_CALL_COUNT, seconds=3)
    write_result_section(
        "backpressure.md",
        f"{BURST_CALL_COUNT} concurrent calls, queue limit {SMALL_QUEUE_SIZE}, 1 worker",
        f"Succeeded: {outcomes.succeeded_count}, rejected with 'queue is full': "
        f"{outcomes.rejected_count}",
    )

    assert outcomes.rejected_count >= 1
    assert outcomes.succeeded_count + outcomes.rejected_count == BURST_CALL_COUNT
