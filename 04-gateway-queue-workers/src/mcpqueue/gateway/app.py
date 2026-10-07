"""Builds the gateway: FastMCP server, job bus, and the ASGI app that connects them."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcpqueue.config import GatewaySettings
from mcpqueue.constants import (
    HEALTH_CHECK_BODY,
    HEALTH_CHECK_PATH,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
)
from mcpqueue.gateway.event_store import InMemoryEventStore
from mcpqueue.gateway.gateway_tools import GatewayTools
from mcpqueue.gateway.job_bus import JobBus, NatsJobBus
from mcpqueue.gateway.job_runner import JobRunner


async def report_health(request: Request) -> JSONResponse:
    return JSONResponse(HEALTH_CHECK_BODY)


class GatewayLifespan:
    """Connects the job bus before MCP sessions start and closes it after they end."""

    def __init__(self, mcp: FastMCP, job_bus: JobBus) -> None:
        self._mcp = mcp
        self._job_bus = job_bus

    @asynccontextmanager
    async def run(self, app: Starlette) -> AsyncIterator[None]:
        await self._job_bus.connect()
        try:
            async with self._mcp.session_manager.run():
                yield
        finally:
            await self._job_bus.close()


def create_gateway_server(settings: GatewaySettings, job_bus: JobBus) -> FastMCP:
    event_store = InMemoryEventStore(
        max_events_per_stream=settings.event_store_max_events_per_stream,
        max_streams=settings.event_store_max_streams,
    )
    mcp = FastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        event_store=event_store,
        host=settings.host,
        port=settings.port,
        session_idle_timeout=settings.session_idle_timeout_seconds,
        log_level=settings.log_level,
    )
    GatewayTools(JobRunner(settings, job_bus)).register(mcp)
    mcp.custom_route(HEALTH_CHECK_PATH, methods=["GET"])(report_health)
    return mcp


def create_gateway_app(settings: GatewaySettings, job_bus: JobBus) -> Starlette:
    mcp = create_gateway_server(settings, job_bus)
    app = mcp.streamable_http_app()
    app.router.lifespan_context = GatewayLifespan(mcp, job_bus).run
    return app


def create_gateway_app_from_env() -> Starlette:
    """Uvicorn factory."""
    settings = GatewaySettings()
    return create_gateway_app(settings, NatsJobBus(settings))
