"""The tool code. It never talks to MCP clients: it reports through a ``JobContext``."""

import os
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from mcpqueue.config import WorkerSettings
from mcpqueue.constants import (
    CONFIRMATION_ANSWER_CONFIRMED,
    CONFIRMATION_ANSWER_DECLINED,
    ELICITATION_ACTION_ACCEPT,
    TOOL_ASK_CONFIRMATION,
    TOOL_GET_REPLICA_ID,
    TOOL_INCREMENT_COUNTER,
    TOOL_RUN_SLOW_JOB,
)
from mcpqueue.job_messages import ElicitationAnswer, JobRequest, JobResult
from mcpqueue.schemas import ReplicaIdentity
from mcpqueue.worker.session_counters import SessionCounterStore


class JobCancelledError(RuntimeError):
    """The gateway cancelled the job (the client cancelled its tool call)."""


class UnknownToolError(ValueError):
    pass


class JobContext(Protocol):
    async def report_progress(self, progress: float, total: float, message: str) -> None: ...

    async def wait_for_answer(self, question: str) -> ElicitationAnswer:
        """Variant A: ask through the gateway and block this worker until the answer arrives."""
        ...

    async def request_continuation(self, question: str, state: dict[str, Any]) -> None:
        """Variant B: ask through the gateway; the answer comes back as a new job."""
        ...

    async def sleep_unless_cancelled(self, seconds: float) -> bool:
        """Sleep; return False as soon as the job is cancelled."""
        ...


def describe_answer(answer: ElicitationAnswer) -> str:
    if answer.action != ELICITATION_ACTION_ACCEPT:
        return answer.action
    if (answer.content or {}).get("confirmed"):
        return CONFIRMATION_ANSWER_CONFIRMED
    return CONFIRMATION_ANSWER_DECLINED


class ToolHandlers:
    """One method per tool. Returns the result, or None when a continuation job will finish it."""

    def __init__(self, settings: WorkerSettings, counter_store: SessionCounterStore) -> None:
        self._settings = settings
        self._counter_store = counter_store
        self._handlers: dict[str, Callable[[JobRequest, JobContext], Awaitable[Any]]] = {
            TOOL_GET_REPLICA_ID: self.get_replica_id,
            TOOL_INCREMENT_COUNTER: self.increment_counter,
            TOOL_RUN_SLOW_JOB: self.run_slow_job,
            TOOL_ASK_CONFIRMATION: self.ask_confirmation,
        }

    async def handle(self, job: JobRequest, job_context: JobContext) -> JobResult | None:
        handler = self._handlers.get(job.tool_name)
        if handler is None:
            raise UnknownToolError(f"unknown tool {job.tool_name!r}")
        return await handler(job, job_context)

    async def get_replica_id(self, job: JobRequest, job_context: JobContext) -> JobResult:
        identity = ReplicaIdentity(replica_id=self._settings.replica_id, process_id=os.getpid())
        return JobResult(result=identity.model_dump())

    async def increment_counter(self, job: JobRequest, job_context: JobContext) -> JobResult:
        return JobResult(result=await self._counter_store.increment(job.session_key, job.job_id))

    async def run_slow_job(self, job: JobRequest, job_context: JobContext) -> JobResult:
        seconds = int(job.arguments["seconds"])
        if not 1 <= seconds <= self._settings.slow_job_max_seconds:
            raise ValueError(f"seconds must be between 1 and {self._settings.slow_job_max_seconds}")
        for completed_seconds in range(1, seconds + 1):
            if not await job_context.sleep_unless_cancelled(self._settings.slow_job_step_seconds):
                raise JobCancelledError(job.job_id)
            await job_context.report_progress(
                completed_seconds,
                seconds,
                f"{completed_seconds}/{seconds} seconds done on {self._settings.replica_id}",
            )
        return JobResult(result=f"slow job finished after {seconds} seconds")

    async def ask_confirmation(self, job: JobRequest, job_context: JobContext) -> JobResult | None:
        if job.continuation is not None:
            return JobResult(result=describe_answer(job.continuation.answer))
        question = job.arguments["question"]
        if self._settings.elicitation_mode == "continuation":
            await job_context.request_continuation(question, {"question": question})
            return None
        answer = await job_context.wait_for_answer(question)
        return JobResult(result=describe_answer(answer))
