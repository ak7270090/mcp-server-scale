"""MCP client helpers for integration tests: sessions, worker logs, progress, answers."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import anyio
import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from tests.integration.stack_control import GATEWAY_URL

REQUEST_TIMEOUT_SECONDS = 120
JOB_LOG_PATTERN = re.compile(r"job (?P<job_id>\w+) attempt (?P<attempt>\d+) on (?P<worker>\S+)")


class WorkerLog:
    """Collects the gateway's "job … attempt N on worker" log notifications."""

    def __init__(self) -> None:
        self.attempts: list[tuple[int, str]] = []

    async def record(self, params: types.LoggingMessageNotificationParams) -> None:
        match = JOB_LOG_PATTERN.search(str(params.data))
        if match:
            self.attempts.append((int(match["attempt"]), match["worker"]))

    @property
    def latest_worker(self) -> str:
        return self.attempts[-1][1]


class ProgressLog:
    """Progress values seen by the client; ``has_reached_target`` fires at ``target_count``."""

    def __init__(self, target_count: int | None = None) -> None:
        self._target_count = target_count
        self.progress_values: list[float] = []
        self.has_reached_target = anyio.Event()

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress_values.append(progress)
        if self._target_count is not None and len(self.progress_values) >= self._target_count:
            self.has_reached_target.set()


@asynccontextmanager
async def open_gateway_session(
    elicitation_callback: Callable[..., Awaitable[types.ElicitResult]] | None = None,
    logging_callback: Callable[..., Awaitable[None]] | None = None,
    message_handler: Callable[..., Awaitable[None]] | None = None,
) -> AsyncIterator[ClientSession]:
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(30, read=REQUEST_TIMEOUT_SECONDS)) as http_client,
        streamable_http_client(GATEWAY_URL, http_client=http_client) as (read, write, _),
        ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=REQUEST_TIMEOUT_SECONDS),
            elicitation_callback=elicitation_callback,
            logging_callback=logging_callback,
            message_handler=message_handler,
        ) as session,
    ):
        await session.initialize()
        yield session
