"""The MCP side: a low-level server whose tool list comes from the registry at request time."""

from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError

from apigateway.config import GatewaySettings
from apigateway.constants import PASSTHROUGH_HEADERS, SERVER_INSTRUCTIONS, SERVER_NAME
from apigateway.discovery_tools import DiscoveryTools
from apigateway.tool_registry import ToolRegistry
from apigateway.tool_router import CallContext, ToolRouter, UnknownToolError


class McpProgressReporter:
    """Sends progress notifications for the current request, if the client asked for them."""

    def __init__(self, request_context: RequestContext) -> None:
        self._request_context = request_context

    async def report(self, progress: float, total: float | None, message: str | None) -> None:
        meta = self._request_context.meta
        progress_token = meta.progressToken if meta else None
        if progress_token is None:
            return
        await self._request_context.session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            related_request_id=str(self._request_context.request_id),
        )


def read_passthrough_headers(request_context: RequestContext) -> dict[str, str]:
    request = request_context.request
    if request is None:
        return {}
    return {name: request.headers[name] for name in PASSTHROUGH_HEADERS if name in request.headers}


class GatewayMcpServer:
    def __init__(
        self,
        settings: GatewaySettings,
        registry: ToolRegistry,
        router: ToolRouter,
        discovery_tools: DiscoveryTools,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._router = router
        self._discovery_tools = discovery_tools
        self.server: Server[Any, Any] = Server(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
        self.server.list_tools()(self.list_tools)
        # Own handler instead of @server.call_tool(): that decorator turns every exception into
        # an isError result, and an unknown tool must be a JSON-RPC error.
        self.server.request_handlers[types.CallToolRequest] = self.handle_call_tool

    async def list_tools(self) -> list[types.Tool]:
        if self._settings.is_discovery_mode:
            return self._discovery_tools.list_mcp_tools()
        return [tool.to_mcp_tool() for tool in self._registry.enabled_tools()]

    async def handle_call_tool(self, request: types.CallToolRequest) -> types.ServerResult:
        request_context = self.server.request_context
        call_context = CallContext(
            passthrough_headers=read_passthrough_headers(request_context),
            progress_reporter=McpProgressReporter(request_context),
        )
        tool_handler = self._discovery_tools if self._settings.is_discovery_mode else self._router
        try:
            result = await tool_handler.call_tool(
                request.params.name, request.params.arguments or {}, call_context
            )
        except UnknownToolError as error:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS, message=f"unknown tool {request.params.name!r}"
                )
            ) from error
        return types.ServerResult(result)
