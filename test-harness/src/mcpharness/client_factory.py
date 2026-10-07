"""Opens MCP client sessions (SDK client) and raw HTTP clients against the target server."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import httpx
from mcp import ClientSession
from mcp.client.session import ElicitationFnT
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from mcpharness.config import HarnessSettings
from mcpharness.constants import (
    DEFAULT_PROTOCOL_VERSION,
    HARNESS_CLIENT_NAME,
    HARNESS_CLIENT_VERSION,
    SESSION_ID_HEADER,
)
from mcpharness.raw_protocol import (
    build_initialize_request,
    build_initialized_notification,
    build_mcp_headers,
    extract_jsonrpc_messages,
    find_response,
)


@dataclass
class McpConnection:
    session: ClientSession
    get_session_id: Callable[[], str | None]


@dataclass(frozen=True)
class RawMcpSession:
    """A session opened with hand-built requests, for checks below the SDK client."""

    session_id: str
    protocol_version: str

    def headers(self) -> dict[str, str]:
        return build_mcp_headers(self.session_id, self.protocol_version)


def create_http_client(settings: HarnessSettings) -> httpx.AsyncClient:
    """HTTP client whose connection reuse is configurable, to expose per-connection routing."""
    keepalive_connections = None if settings.reuse_connections else 0
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            settings.request_timeout_seconds, read=settings.stream_read_timeout_seconds
        ),
        limits=httpx.Limits(max_keepalive_connections=keepalive_connections),
    )


@asynccontextmanager
async def create_mcp_connection(
    settings: HarnessSettings, elicitation_callback: ElicitationFnT | None = None
) -> AsyncIterator[McpConnection]:
    """An initialized SDK client session; the session is deleted on exit."""
    async with (
        create_http_client(settings) as http_client,
        streamable_http_client(settings.target_url, http_client=http_client) as (
            read_stream,
            write_stream,
            get_session_id,
        ),
        ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=settings.request_timeout_seconds),
            elicitation_callback=elicitation_callback,
            client_info=Implementation(name=HARNESS_CLIENT_NAME, version=HARNESS_CLIENT_VERSION),
        ) as session,
    ):
        await session.initialize()
        yield McpConnection(session=session, get_session_id=get_session_id)


async def open_raw_session(http_client: httpx.AsyncClient, target_url: str) -> RawMcpSession:
    """Send ``initialize`` and ``notifications/initialized`` by hand and return the session."""
    initialize_request_id = 1
    response = await http_client.post(
        target_url,
        json=build_initialize_request(initialize_request_id, DEFAULT_PROTOCOL_VERSION),
        headers=build_mcp_headers(),
    )
    response.raise_for_status()
    messages = extract_jsonrpc_messages(response.headers.get("content-type", ""), response.text)
    initialize_response = find_response(messages, initialize_request_id)
    raw_session = RawMcpSession(
        session_id=response.headers[SESSION_ID_HEADER],
        protocol_version=initialize_response["result"]["protocolVersion"],
    )
    initialized_response = await http_client.post(
        target_url, json=build_initialized_notification(), headers=raw_session.headers()
    )
    initialized_response.raise_for_status()
    return raw_session
