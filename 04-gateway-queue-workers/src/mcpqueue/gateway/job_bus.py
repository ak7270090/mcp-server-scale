"""How the gateway talks to the workers: submit jobs, read their messages, answer, cancel."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

import nats.errors
from nats.aio.client import Client as NatsClient
from nats.aio.subscription import Subscription
from nats.js import JetStreamContext
from nats.js.errors import APIError

from mcpqueue.config import QueueSettings
from mcpqueue.constants import JOB_SUBJECT, MESSAGE_ID_HEADER
from mcpqueue.job_messages import (
    ElicitationAnswer,
    JobRequest,
    WorkerMessage,
    build_answers_subject,
    build_cancel_subject,
    build_results_subject,
    parse_worker_message,
)
from mcpqueue.nats_client import create_nats_connection, ensure_job_streams

QUEUE_FULL_ERROR_CODES = frozenset({10077})


class QueueFullError(RuntimeError):
    """The job stream is at ``queue_max_pending``; the job was not queued."""


class ResultSubscription(Protocol):
    async def next_message(self, timeout_seconds: float) -> WorkerMessage:
        """Next message for the job; raises ``TimeoutError`` if none arrives in time."""
        ...


class JobBus(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def submit_job(self, job: JobRequest) -> None: ...

    def open_results(self, job_id: str) -> AbstractAsyncContextManager[ResultSubscription]: ...

    async def send_answer(self, job_id: str, answer: ElicitationAnswer) -> None: ...

    async def send_cancel(self, job_id: str) -> None: ...


class NatsResultSubscription:
    def __init__(self, subscription: Subscription) -> None:
        self._subscription = subscription

    async def next_message(self, timeout_seconds: float) -> WorkerMessage:
        try:
            nats_message = await self._subscription.next_msg(timeout=timeout_seconds)
        except nats.errors.TimeoutError as error:
            raise TimeoutError from error
        return parse_worker_message(nats_message.data)


class NatsJobBus:
    """Jobs go on the JetStream work queue; worker messages, answers and cancels on core NATS."""

    def __init__(self, settings: QueueSettings) -> None:
        self._settings = settings
        self._connection: NatsClient | None = None
        self._jetstream: JetStreamContext | None = None

    async def connect(self) -> None:
        self._connection = await create_nats_connection(self._settings)
        self._jetstream = self._connection.jetstream()
        await ensure_job_streams(self._jetstream, self._settings)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.drain()

    async def submit_job(self, job: JobRequest) -> None:
        try:
            await self._jetstream.publish(
                JOB_SUBJECT,
                job.model_dump_json().encode(),
                headers={MESSAGE_ID_HEADER: job.job_id},
            )
        except APIError as error:
            if error.err_code in QUEUE_FULL_ERROR_CODES:
                raise QueueFullError(error.description) from error
            raise

    @asynccontextmanager
    async def open_results(self, job_id: str) -> AsyncIterator[ResultSubscription]:
        subscription = await self._connection.subscribe(build_results_subject(job_id))
        try:
            yield NatsResultSubscription(subscription)
        finally:
            await subscription.unsubscribe()

    async def send_answer(self, job_id: str, answer: ElicitationAnswer) -> None:
        await self._connection.publish(
            build_answers_subject(job_id), answer.model_dump_json().encode()
        )

    async def send_cancel(self, job_id: str) -> None:
        await self._connection.publish(build_cancel_subject(job_id), b"")
