from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
import pytest

from mcpharness.client_factory import RawMcpSession, create_http_client, open_raw_session
from mcpharness.config import HarnessSettings
from mcpharness.constants import LAST_EVENT_ID_HEADER, METHOD_PROGRESS, TOOL_RUN_SLOW_JOB
from mcpharness.raw_protocol import SseEventAccumulator, build_tool_call_request

pytestmark = [pytest.mark.anyio, pytest.mark.resumability]

SLOW_JOB_REQUEST_ID = 10
PROGRESS_TOKEN = "resumability-check"


@dataclass
class StreamObservation:
    """What one SSE stream delivered before it ended or we dropped it."""

    progress_values: list[float] = field(default_factory=list)
    last_event_id: str | None = None
    final_response: dict[str, Any] | None = None

    def record(self, message: dict[str, Any] | None, event_id: str | None) -> None:
        if event_id is not None:
            self.last_event_id = event_id
        if message is None:
            return
        if message.get("method") == METHOD_PROGRESS:
            self.progress_values.append(message["params"]["progress"])
        elif message.get("id") == SLOW_JOB_REQUEST_ID:
            self.final_response = message


async def read_stream(
    response: httpx.Response, observation: StreamObservation, stop_after_progress: int | None
) -> None:
    accumulator = SseEventAccumulator()
    async for line in response.aiter_lines():
        sse_event = accumulator.feed_line(line)
        if sse_event is None:
            continue
        observation.record(sse_event.jsonrpc_message(), sse_event.event_id)
        if observation.final_response is not None:
            return
        if (
            stop_after_progress is not None
            and len(observation.progress_values) >= stop_after_progress
        ):
            return


async def start_slow_job_then_disconnect(
    http_client: httpx.AsyncClient,
    settings: HarnessSettings,
    raw_session: RawMcpSession,
    observation: StreamObservation,
) -> None:
    request = build_tool_call_request(
        TOOL_RUN_SLOW_JOB,
        {"seconds": settings.slow_job_seconds},
        SLOW_JOB_REQUEST_ID,
        progress_token=PROGRESS_TOKEN,
    )
    async with http_client.stream(
        "POST", settings.target_url, json=request, headers=raw_session.headers()
    ) as response:
        response.raise_for_status()
        await read_stream(response, observation, settings.resumability_events_before_disconnect)


async def resume_until_complete(
    http_client: httpx.AsyncClient,
    settings: HarnessSettings,
    raw_session: RawMcpSession,
    observation: StreamObservation,
) -> None:
    """Reconnect with the latest event ID until the final response arrives, like an SSE client.

    A resume that reaches the server before it notices the old stream closed is answered
    with the missed events only, then ends; the next reconnect picks up the live stream.
    """
    for _ in range(settings.resumability_max_reconnects):
        headers = {**raw_session.headers(), LAST_EVENT_ID_HEADER: observation.last_event_id}
        async with http_client.stream("GET", settings.target_url, headers=headers) as response:
            response.raise_for_status()
            await read_stream(response, observation, stop_after_progress=None)
        if observation.final_response is not None:
            return
        await anyio.sleep(settings.resumability_reconnect_delay_seconds)


async def test_resumed_stream_misses_no_progress(harness_settings: HarnessSettings) -> None:
    observation = StreamObservation()
    async with create_http_client(harness_settings) as http_client:
        raw_session = await open_raw_session(http_client, harness_settings.target_url)
        await start_slow_job_then_disconnect(
            http_client, harness_settings, raw_session, observation
        )
        assert observation.last_event_id is not None, "server sent no event IDs"
        await resume_until_complete(http_client, harness_settings, raw_session, observation)
        await http_client.delete(harness_settings.target_url, headers=raw_session.headers())

    assert observation.progress_values == [
        float(step) for step in range(1, harness_settings.slow_job_seconds + 1)
    ]
    assert observation.final_response is not None
    assert "result" in observation.final_response
