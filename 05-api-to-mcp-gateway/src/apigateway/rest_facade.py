"""Reverse direction: any MCP server's tools as REST endpoints, plus a generated OpenAPI doc."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from apigateway.constants import (
    FACADE_OPENAPI_PATH,
    FACADE_TOOL_PATH,
    FACADE_TOOLS_PATH,
    PASSTHROUGH_HEADERS,
)

ERROR_SCHEMA_REFERENCE = {"$ref": "#/components/schemas/Error"}


class McpUpstream(Protocol):
    def open_session(
        self, headers: dict[str, str]
    ) -> AbstractAsyncContextManager[ClientSession]: ...


class HttpMcpUpstream:
    """A fresh MCP session per REST request, forwarding Authorization and traceparent."""

    def __init__(self, url: str, timeout_seconds: float) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def open_session(self, headers: dict[str, str]) -> AsyncIterator[ClientSession]:
        async with (
            httpx.AsyncClient(headers=headers, timeout=self._timeout_seconds) as http_client,
            streamable_http_client(self._url, http_client=http_client) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session


def build_error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def describe_tool(tool: types.Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
        "outputSchema": tool.outputSchema,
    }


def build_facade_openapi(tools: list[types.Tool]) -> dict[str, Any]:
    error_responses = {
        str(status_code): {
            "description": description,
            "content": {"application/json": {"schema": ERROR_SCHEMA_REFERENCE}},
        }
        for status_code, description in (
            (400, "Body is not a JSON object"),
            (404, "No such tool"),
            (422, "The tool reported an error"),
            (502, "MCP upstream unavailable"),
        )
    }
    paths: dict[str, Any] = {
        FACADE_TOOLS_PATH: {
            "get": {
                "operationId": "listTools",
                "summary": "List the MCP tools",
                "responses": {"200": {"description": "Tools"}, "502": error_responses["502"]},
            }
        }
    }
    for tool in tools:
        result_schema = tool.outputSchema or {"type": "string"}
        paths[FACADE_TOOL_PATH.format(tool_name=tool.name)] = {
            "post": {
                "operationId": tool.name,
                "summary": tool.description or tool.name,
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": tool.inputSchema}},
                },
                "responses": {
                    "200": {
                        "description": "Tool result",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"result": result_schema},
                                    "required": ["result"],
                                }
                            }
                        },
                    },
                    **error_responses,
                },
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "MCP tools as REST", "version": "1.0.0"},
        "paths": paths,
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {"error": {"type": "string"}},
                    "required": ["error"],
                }
            }
        },
    }


class RestFacade:
    def __init__(self, upstream: McpUpstream) -> None:
        self._upstream = upstream

    def routes(self) -> list[Route]:
        return [
            Route(FACADE_TOOLS_PATH, self.list_tools, methods=["GET"]),
            Route(FACADE_TOOL_PATH, self.call_tool, methods=["POST"]),
            Route(FACADE_OPENAPI_PATH, self.openapi_document, methods=["GET"]),
        ]

    async def list_tools(self, request: Request) -> JSONResponse:
        try:
            tools = await self._fetch_tools(request)
        except Exception as error:
            return build_error_response(502, f"MCP upstream unavailable: {error}")
        return JSONResponse({"tools": [describe_tool(tool) for tool in tools]})

    async def openapi_document(self, request: Request) -> JSONResponse:
        try:
            tools = await self._fetch_tools(request)
        except Exception as error:
            return build_error_response(502, f"MCP upstream unavailable: {error}")
        return JSONResponse(build_facade_openapi(tools))

    async def call_tool(self, request: Request) -> JSONResponse:
        try:
            arguments = await request.json()
        except ValueError:
            return build_error_response(400, "body must be a JSON object")
        if not isinstance(arguments, dict):
            return build_error_response(400, "body must be a JSON object")
        tool_name = request.path_params["tool_name"]
        try:
            async with self._upstream.open_session(read_passthrough_headers(request)) as session:
                outcome = await self._call_upstream_tool(session, tool_name, arguments)
        except Exception as error:
            return build_error_response(502, f"MCP upstream unavailable: {error}")
        return outcome

    @staticmethod
    async def _call_upstream_tool(
        session: ClientSession, tool_name: str, arguments: dict[str, Any]
    ) -> JSONResponse:
        """Builds the response inside the session, so MCP errors never escape its task group."""
        try:
            result = await session.call_tool(tool_name, arguments)
        except McpError as error:
            if error.error.code == types.INVALID_PARAMS:
                return build_error_response(404, error.error.message)
            return build_error_response(502, error.error.message)
        text = " ".join(
            block.text for block in result.content if isinstance(block, types.TextContent)
        )
        if result.isError:
            return build_error_response(422, text)
        if result.structuredContent is not None:
            return JSONResponse({"result": result.structuredContent})
        return JSONResponse({"result": text})

    async def _fetch_tools(self, request: Request) -> list[types.Tool]:
        async with self._upstream.open_session(read_passthrough_headers(request)) as session:
            return (await session.list_tools()).tools


def read_passthrough_headers(request: Request) -> dict[str, str]:
    return {name: request.headers[name] for name in PASSTHROUGH_HEADERS if name in request.headers}
