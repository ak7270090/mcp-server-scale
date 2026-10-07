"""Builds the MCP server and the ASGI app that serves it over Streamable HTTP."""

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http import EventStore
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcpserver.config import ServerSettings
from mcpserver.constants import (
    HEALTH_CHECK_BODY,
    HEALTH_CHECK_PATH,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
)
from mcpserver.event_store import InMemoryEventStore
from mcpserver.session_id_generator import install_replica_prefixed_session_manager
from mcpserver.tools import ReplicaTools, SessionCounterStore
from mcpserver.tracing import enable_tracing


async def report_health(request: Request) -> JSONResponse:
    return JSONResponse(HEALTH_CHECK_BODY)


def create_event_store(settings: ServerSettings) -> InMemoryEventStore:
    return InMemoryEventStore(
        max_events_per_stream=settings.event_store_max_events_per_stream,
        max_streams=settings.event_store_max_streams,
    )


def create_mcp_server(settings: ServerSettings, event_store: EventStore) -> FastMCP:
    mcp = FastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        event_store=event_store,
        host=settings.host,
        port=settings.port,
        session_idle_timeout=settings.session_idle_timeout_seconds,
        log_level=settings.log_level,
    )
    ReplicaTools(settings, SessionCounterStore()).register(mcp)
    mcp.custom_route(HEALTH_CHECK_PATH, methods=["GET"])(report_health)
    return mcp


def create_asgi_app() -> Starlette:
    """Uvicorn factory for one replica, issuing session IDs prefixed with its replica ID."""
    settings = ServerSettings()
    event_store = create_event_store(settings)
    mcp = create_mcp_server(settings, event_store)
    install_replica_prefixed_session_manager(mcp, settings, event_store)
    app = mcp.streamable_http_app()
    enable_tracing(app, settings)
    return app
