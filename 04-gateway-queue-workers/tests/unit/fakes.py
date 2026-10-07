"""Test doubles for the NATS-backed pieces."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from nats.js.errors import KeyNotFoundError, KeyWrongLastSequenceError

from mcpqueue.gateway.job_bus import QueueFullError
from mcpqueue.job_messages import ElicitationAnswer, JobRequest, WorkerMessage

STREAM_BUFFER_SIZE = 100

JobScript = Callable[[JobRequest], list[WorkerMessage]]
AnswerScript = Callable[[str, ElicitationAnswer], list[WorkerMessage]]


class FakeResultSubscription:
    def __init__(self, receive_stream: MemoryObjectReceiveStream[WorkerMessage]) -> None:
        self._receive_stream = receive_stream

    async def next_message(self, timeout_seconds: float) -> WorkerMessage:
        with anyio.fail_after(timeout_seconds):
            return await self._receive_stream.receive()


class FakeJobBus:
    """A scripted worker answers each submitted job (and each answer) with fixed messages."""

    def __init__(
        self,
        job_script: JobScript,
        answer_script: AnswerScript | None = None,
        is_queue_full: bool = False,
    ) -> None:
        self._job_script = job_script
        self._answer_script = answer_script
        self._is_queue_full = is_queue_full
        self._send_streams: dict[str, MemoryObjectSendStream[WorkerMessage]] = {}
        self.submitted_jobs: list[JobRequest] = []
        self.sent_answers: list[tuple[str, ElicitationAnswer]] = []
        self.cancelled_job_ids: list[str] = []
        self.is_connected = False

    async def connect(self) -> None:
        self.is_connected = True

    async def close(self) -> None:
        self.is_connected = False

    async def submit_job(self, job: JobRequest) -> None:
        if self._is_queue_full:
            raise QueueFullError("full")
        self.submitted_jobs.append(job)
        await self._deliver(job.job_id, self._job_script(job))

    @asynccontextmanager
    async def open_results(self, job_id: str) -> AsyncIterator[FakeResultSubscription]:
        send_stream, receive_stream = anyio.create_memory_object_stream[WorkerMessage](
            STREAM_BUFFER_SIZE
        )
        self._send_streams[job_id] = send_stream
        try:
            yield FakeResultSubscription(receive_stream)
        finally:
            del self._send_streams[job_id]

    async def send_answer(self, job_id: str, answer: ElicitationAnswer) -> None:
        self.sent_answers.append((job_id, answer))
        await self._deliver(job_id, self._answer_script(job_id, answer))

    async def send_cancel(self, job_id: str) -> None:
        self.cancelled_job_ids.append(job_id)

    async def _deliver(self, job_id: str, messages: list[WorkerMessage]) -> None:
        for message in messages:
            await self._send_streams[job_id].send(message)


class FakeEntry:
    def __init__(self, value: bytes, revision: int) -> None:
        self.value = value
        self.revision = revision


class FakeCounterBucket:
    """Key-value bucket with compare-and-set; ``conflicts_to_inject`` simulates racing writers."""

    def __init__(self, conflicts_to_inject: int = 0) -> None:
        self._entries: dict[str, FakeEntry] = {}
        self._conflicts_to_inject = conflicts_to_inject

    async def get(self, key: str) -> FakeEntry:
        if key not in self._entries:
            raise KeyNotFoundError
        return self._entries[key]

    async def create(self, key: str, value: bytes) -> int:
        if key in self._entries or self._take_injected_conflict():
            raise KeyWrongLastSequenceError
        self._entries[key] = FakeEntry(value, revision=1)
        return 1

    async def update(self, key: str, value: bytes, last: int | None = None) -> int:
        current = self._entries[key]
        if current.revision != last or self._take_injected_conflict():
            raise KeyWrongLastSequenceError
        self._entries[key] = FakeEntry(value, revision=current.revision + 1)
        return current.revision + 1

    def _take_injected_conflict(self) -> bool:
        if self._conflicts_to_inject == 0:
            return False
        self._conflicts_to_inject -= 1
        return True


class FakeJobContext:
    """Records what a tool handler reports; cancels after ``cancel_after_sleeps`` sleeps."""

    def __init__(
        self, answer: ElicitationAnswer | None = None, cancel_after_sleeps: int | None = None
    ) -> None:
        self._answer = answer
        self._cancel_after_sleeps = cancel_after_sleeps
        self.sleep_count = 0
        self.progress_values: list[float] = []
        self.questions_waited_on: list[str] = []
        self.continuations_requested: list[tuple[str, dict[str, Any]]] = []

    async def report_progress(self, progress: float, total: float, message: str) -> None:
        self.progress_values.append(progress)

    async def wait_for_answer(self, question: str) -> ElicitationAnswer:
        self.questions_waited_on.append(question)
        return self._answer

    async def request_continuation(self, question: str, state: dict[str, Any]) -> None:
        self.continuations_requested.append((question, state))

    async def sleep_unless_cancelled(self, seconds: float) -> bool:
        self.sleep_count += 1
        return self._cancel_after_sleeps is None or self.sleep_count <= self._cancel_after_sleeps
