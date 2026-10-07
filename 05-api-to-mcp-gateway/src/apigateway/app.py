"""Wires control plane, data plane, MCP endpoint, REST facade and admin routes into one app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from apigateway.config import GatewaySettings
from apigateway.constants import HEALTH_CHECK_BODY, HEALTH_CHECK_PATH, MCP_PATH, REGISTRY_PATH
from apigateway.discovery_tools import DiscoveryTools
from apigateway.grpc_invoker import GrpcInvoker
from apigateway.mcp_server import GatewayMcpServer
from apigateway.response_filters import ResponseFilter
from apigateway.rest_facade import HttpMcpUpstream, McpUpstream, RestFacade
from apigateway.rest_invoker import RestInvoker
from apigateway.service_crawler import ServiceCrawler
from apigateway.tool_registry import RegistryRefresher, ToolCrawler, ToolRegistry
from apigateway.tool_router import ToolRouter


class McpEndpoint:
    """ASGI endpoint handing ``/mcp`` requests to the session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


class AdminRoutes:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def routes(self) -> list[Route]:
        return [
            Route(HEALTH_CHECK_PATH, self.report_health, methods=["GET"]),
            Route(REGISTRY_PATH, self.list_registry, methods=["GET"]),
        ]

    async def report_health(self, request: Request) -> JSONResponse:
        return JSONResponse(HEALTH_CHECK_BODY)

    async def list_registry(self, request: Request) -> JSONResponse:
        """Every discovered tool and whether it is enabled — what a reviewer curates from."""
        return JSONResponse({"tools": self._registry.describe_discovered_tools()})


class GatewayLifespan:
    def __init__(
        self,
        registry: ToolRegistry,
        refresher: RegistryRefresher,
        session_manager: StreamableHTTPSessionManager,
        http_client: httpx.AsyncClient,
        grpc_invoker: GrpcInvoker,
    ) -> None:
        self._registry = registry
        self._refresher = refresher
        self._session_manager = session_manager
        self._http_client = http_client
        self._grpc_invoker = grpc_invoker

    @asynccontextmanager
    async def run(self, app: Starlette) -> AsyncIterator[None]:
        await self._registry.refresh()
        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(self._refresher.run_forever)
                async with self._session_manager.run():
                    yield
                task_group.cancel_scope.cancel()
        finally:
            await self._grpc_invoker.close()
            await self._http_client.aclose()


def create_gateway_app(
    settings: GatewaySettings,
    crawler: ToolCrawler | None = None,
    upstream: McpUpstream | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> Starlette:
    http_client = http_client or httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    registry = ToolRegistry(settings, crawler or ServiceCrawler(settings, http_client))
    grpc_invoker = GrpcInvoker(settings)
    router = ToolRouter(
        settings,
        registry,
        RestInvoker(http_client),
        grpc_invoker,
        ResponseFilter(settings.redaction_patterns),
    )
    mcp_server = GatewayMcpServer(
        settings, registry, router, DiscoveryTools(settings, registry, router)
    )
    session_manager = StreamableHTTPSessionManager(app=mcp_server.server)
    facade = RestFacade(
        upstream or HttpMcpUpstream(settings.facade_upstream_url, settings.facade_timeout_seconds)
    )
    lifespan = GatewayLifespan(
        registry,
        RegistryRefresher(registry, settings.registry_refresh_seconds),
        session_manager,
        http_client,
        grpc_invoker,
    )
    routes = [
        Route(MCP_PATH, endpoint=McpEndpoint(session_manager)),
        *AdminRoutes(registry).routes(),
        *facade.routes(),
    ]
    return Starlette(routes=routes, lifespan=lifespan.run)


def create_gateway_app_from_env() -> Starlette:
    """Uvicorn factory."""
    return create_gateway_app(GatewaySettings())
