"""Runs one tool call as one or more queued jobs and relays worker messages to the MCP client."""

from typing import Any

import anyio
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from mcpqueue.config import GatewaySettings
from mcpqueue.constants import (
    ELICITATION_ACTION_ACCEPT,
    LOCAL_SESSION_KEY_PREFIX,
    SESSION_ID_HEADER,
)
from mcpqueue.gateway.job_bus import JobBus, QueueFullError
from mcpqueue.job_messages import (
    Continuation,
    ElicitationAnswer,
    JobFailed,
    JobInputRequired,
    JobProgress,
    JobRequest,
    JobResult,
    JobStarted,
)
from mcpqueue.schemas import ConfirmationAnswer


def read_session_key(ctx: Context) -> str:
    """The MCP session ID over HTTP; a per-session local key when there is no HTTP request."""
    request = ctx.request_context.request
    session_id = request.headers.get(SESSION_ID_HEADER) if request is not None else None
    return session_id or f"{LOCAL_SESSION_KEY_PREFIX}{id(ctx.session)}"


class ProgressRelay:
    """Forwards only increasing progress; a redelivered job restarts its count from 1."""

    def __init__(self) -> None:
        self.last_progress = 0.0

    async def forward(self, message: JobProgress, ctx: Context) -> None:
        if message.progress <= self.last_progress:
            return
        self.last_progress = message.progress
        await ctx.report_progress(message.progress, message.total, message.message)


class JobRunner:
    def __init__(self, settings: GatewaySettings, job_bus: JobBus) -> None:
        self._settings = settings
        self._job_bus = job_bus

    async def run_tool(self, tool_name: str, arguments: dict[str, Any], ctx: Context) -> Any:
        job = JobRequest(
            tool_name=tool_name, arguments=arguments, session_key=read_session_key(ctx)
        )
        progress_relay = ProgressRelay()
        while True:
            outcome = await self._run_job(job, ctx, progress_relay)
            if isinstance(outcome, JobResult):
                return outcome.result
            job = outcome

    async def _run_job(
        self, job: JobRequest, ctx: Context, progress_relay: ProgressRelay
    ) -> JobResult | JobRequest:
        """Relay one job's messages until it returns a result or asks for a continuation job."""
        is_finished = False
        async with self._job_bus.open_results(job.job_id) as results:
            await self._submit(job)
            try:
                while True:
                    message = await self._next_message(results, job)
                    if isinstance(message, JobStarted):
                        await ctx.info(
                            f"job {job.job_id} attempt {message.delivery_attempt} "
                            f"on {message.worker_id}"
                        )
                    elif isinstance(message, JobProgress):
                        await progress_relay.forward(message, ctx)
                    elif isinstance(message, JobInputRequired):
                        answer = await self._ask_user(message.question, ctx)
                        if message.continuation_state is None:
                            await self._job_bus.send_answer(job.job_id, answer)
                            continue
                        is_finished = True
                        return self._build_continuation_job(job, message, answer)
                    elif isinstance(message, JobResult):
                        is_finished = True
                        return message
                    elif isinstance(message, JobFailed):
                        is_finished = True
                        raise ToolError(message.error)
            finally:
                if not is_finished:
                    with anyio.CancelScope(shield=True):
                        await self._job_bus.send_cancel(job.job_id)

    async def _submit(self, job: JobRequest) -> None:
        try:
            await self._job_bus.submit_job(job)
        except QueueFullError as error:
            raise ToolError("job queue is full; retry later") from error

    async def _next_message(self, results, job: JobRequest):
        try:
            return await results.next_message(self._settings.job_message_timeout_seconds)
        except TimeoutError as error:
            raise ToolError(
                f"no message from workers for job {job.job_id} within "
                f"{self._settings.job_message_timeout_seconds} seconds"
            ) from error

    @staticmethod
    async def _ask_user(question: str, ctx: Context) -> ElicitationAnswer:
        elicitation = await ctx.elicit(question, ConfirmationAnswer)
        content = (
            elicitation.data.model_dump()
            if elicitation.action == ELICITATION_ACTION_ACCEPT
            else None
        )
        return ElicitationAnswer(action=elicitation.action, content=content)

    @staticmethod
    def _build_continuation_job(
        job: JobRequest, message: JobInputRequired, answer: ElicitationAnswer
    ) -> JobRequest:
        return JobRequest(
            tool_name=job.tool_name,
            arguments=job.arguments,
            session_key=job.session_key,
            continuation=Continuation(state=message.continuation_state, answer=answer),
        )
