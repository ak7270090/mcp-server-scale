"""Pulls one job at a time, heartbeats while it runs, and acks, terminates or dead-letters it."""

import asyncio
import contextlib
import logging
from typing import Any

from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription
from nats.js import JetStreamContext
from nats.js.errors import FetchTimeoutError
from pydantic import BaseModel

from mcpqueue.config import WorkerSettings
from mcpqueue.constants import (
    DEAD_LETTER_SUBJECT,
    JOB_CONSUMER_NAME,
    JOB_STREAM_NAME,
    JOB_SUBJECT,
)
from mcpqueue.job_messages import (
    ElicitationAnswer,
    JobFailed,
    JobInputRequired,
    JobProgress,
    JobRequest,
    JobStarted,
    build_answers_subject,
    build_cancel_subject,
    build_results_subject,
)
from mcpqueue.nats_client import (
    create_nats_connection,
    ensure_job_streams,
    open_session_counter_bucket,
)
from mcpqueue.worker.session_counters import SessionCounterStore
from mcpqueue.worker.tool_handlers import JobCancelledError, ToolHandlers

logger = logging.getLogger(__name__)


class NatsJobContext:
    """What a running job can do: report progress, ask the user, notice cancellation."""

    def __init__(self, connection: NatsClient, job: JobRequest, settings: WorkerSettings) -> None:
        self._connection = connection
        self._job = job
        self._settings = settings
        self._cancelled = asyncio.Event()

    async def publish(self, message: BaseModel) -> None:
        await self._connection.publish(
            build_results_subject(self._job.job_id), message.model_dump_json().encode()
        )

    async def watch_for_cancel(self, subscription: Subscription) -> None:
        async for _ in subscription.messages:
            self._cancelled.set()
            return

    async def report_progress(self, progress: float, total: float, message: str) -> None:
        await self.publish(JobProgress(progress=progress, total=total, message=message))

    async def wait_for_answer(self, question: str) -> ElicitationAnswer:
        answers = await self._connection.subscribe(build_answers_subject(self._job.job_id))
        try:
            await self.publish(JobInputRequired(question=question))
            answer_message = await answers.next_msg(timeout=self._settings.answer_timeout_seconds)
        finally:
            await answers.unsubscribe()
        return ElicitationAnswer.model_validate_json(answer_message.data)

    async def request_continuation(self, question: str, state: dict[str, Any]) -> None:
        await self.publish(JobInputRequired(question=question, continuation_state=state))

    async def sleep_unless_cancelled(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._cancelled.wait(), timeout=seconds)
        except TimeoutError:
            return True
        return False


class JobConsumer:
    def __init__(self, settings: WorkerSettings) -> None:
        self._settings = settings
        self._is_stop_requested = False
        self._connection: NatsClient | None = None
        self._jetstream: JetStreamContext | None = None

    def request_stop(self) -> None:
        """Finish the current job, then exit (SIGTERM)."""
        logger.info("worker %s stop requested", self._settings.replica_id)
        self._is_stop_requested = True

    async def run(self) -> None:
        self._connection = await create_nats_connection(self._settings)
        self._jetstream = self._connection.jetstream()
        await ensure_job_streams(self._jetstream, self._settings)
        counter_bucket = await open_session_counter_bucket(self._jetstream, self._settings)
        handlers = ToolHandlers(self._settings, SessionCounterStore(counter_bucket))
        subscription = await self._jetstream.pull_subscribe(
            JOB_SUBJECT, durable=JOB_CONSUMER_NAME, stream=JOB_STREAM_NAME
        )
        logger.info("worker %s waiting for jobs", self._settings.replica_id)
        try:
            while not self._is_stop_requested:
                try:
                    messages = await subscription.fetch(
                        1, timeout=self._settings.fetch_timeout_seconds
                    )
                except (FetchTimeoutError, TimeoutError):
                    continue
                for message in messages:
                    await self._process(message, handlers)
        finally:
            await self._connection.close()
            logger.info("worker %s stopped", self._settings.replica_id)

    async def _process(self, message: Msg, handlers: ToolHandlers) -> None:
        job = JobRequest.model_validate_json(message.data)
        job_context = NatsJobContext(self._connection, job, self._settings)
        delivery_attempt = message.metadata.num_delivered
        if delivery_attempt > self._settings.job_max_deliveries:
            await self._move_to_dead_letters(message, job_context, delivery_attempt)
            return
        logger.info("job %s %s attempt %d", job.job_id, job.tool_name, delivery_attempt)
        await job_context.publish(
            JobStarted(worker_id=self._settings.replica_id, delivery_attempt=delivery_attempt)
        )
        cancel_subscription = await self._connection.subscribe(build_cancel_subject(job.job_id))
        background_tasks = [
            asyncio.create_task(self._send_heartbeats(message)),
            asyncio.create_task(job_context.watch_for_cancel(cancel_subscription)),
        ]
        try:
            outcome = await handlers.handle(job, job_context)
            if outcome is not None:
                await job_context.publish(outcome)
            await message.ack()
        except JobCancelledError:
            logger.info("job %s cancelled", job.job_id)
            await message.term()
        except Exception as error:
            await job_context.publish(JobFailed(error=str(error)))
            await message.term()
        finally:
            for task in background_tasks:
                task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await cancel_subscription.unsubscribe()

    async def _send_heartbeats(self, message: Msg) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_seconds)
            await message.in_progress()

    async def _move_to_dead_letters(
        self, message: Msg, job_context: NatsJobContext, delivery_attempt: int
    ) -> None:
        await self._jetstream.publish(DEAD_LETTER_SUBJECT, message.data)
        await job_context.publish(
            JobFailed(error=f"job moved to dead letters after {delivery_attempt - 1} deliveries")
        )
        await message.term()
