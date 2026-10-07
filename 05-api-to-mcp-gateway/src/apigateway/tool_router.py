"""Data plane: one tool call → validate → invoke (with retries) → filter → MCP result."""

import json
from dataclasses import dataclass, field
from typing import Any

import anyio
import jsonschema
from mcp import types

from apigateway.config import GatewaySettings
from apigateway.constants import EMPTY_RESULT_TEXT, FIELDS_ARGUMENT, WRAPPED_RESULT_KEY
from apigateway.error_mapping import BackendCallError
from apigateway.grpc_invoker import GrpcInvoker, ProgressReporter
from apigateway.response_filters import ResponseFilter
from apigateway.rest_invoker import RestInvoker
from apigateway.tool_definitions import RestRoute, ToolDefinition
from apigateway.tool_registry import ToolRegistry


class UnknownToolError(LookupError):
    """No enabled tool has this name; becomes a JSON-RPC error, not a tool result."""


class NoProgressReporter:
    async def report(self, progress: float, total: float | None, message: str | None) -> None:
        return None


@dataclass
class CallContext:
    passthrough_headers: dict[str, str] = field(default_factory=dict)
    progress_reporter: ProgressReporter = field(default_factory=NoProgressReporter)


def build_error_result(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=True)


def build_structured_result(structured: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(structured))],
        structuredContent=structured,
    )


class ToolRouter:
    def __init__(
        self,
        settings: GatewaySettings,
        registry: ToolRegistry,
        rest_invoker: RestInvoker,
        grpc_invoker: GrpcInvoker,
        response_filter: ResponseFilter,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._rest_invoker = rest_invoker
        self._grpc_invoker = grpc_invoker
        self._response_filter = response_filter

    async def call_tool(
        self, name: str, arguments: dict[str, Any], call_context: CallContext
    ) -> types.CallToolResult:
        tool = self._registry.find_enabled_tool(name)
        if tool is None:
            raise UnknownToolError(name)
        validation_error = jsonschema.exceptions.best_match(
            tool.input_validator.iter_errors(arguments)
        )
        if validation_error is not None:
            return build_error_result(f"invalid arguments: {validation_error.message}")
        backend_arguments = dict(arguments)
        fields = backend_arguments.pop(FIELDS_ARGUMENT, None)
        try:
            raw_result = await self._invoke_with_retries(tool, backend_arguments, call_context)
        except BackendCallError as error:
            return build_error_result(error.failure.to_tool_error_text())
        return self._build_result(tool, raw_result, fields)

    async def _invoke_with_retries(
        self, tool: ToolDefinition, arguments: dict[str, Any], call_context: CallContext
    ) -> Any:
        """Retry only read-only tools, and only failures marked retryable."""
        attempt_count = 1 + (self._settings.read_only_retry_attempts if tool.is_read_only else 0)
        for attempt in range(1, attempt_count + 1):
            try:
                return await self._invoke(tool, arguments, call_context)
            except BackendCallError as error:
                if not error.failure.is_retryable or attempt == attempt_count:
                    raise
                await anyio.sleep(self._settings.retry_backoff_seconds * attempt)
        raise AssertionError("unreachable")

    async def _invoke(
        self, tool: ToolDefinition, arguments: dict[str, Any], call_context: CallContext
    ) -> Any:
        if isinstance(tool.route, RestRoute):
            return await self._rest_invoker.invoke(
                tool.route, arguments, call_context.passthrough_headers
            )
        return await self._grpc_invoker.invoke(
            tool.route, arguments, call_context.passthrough_headers, call_context.progress_reporter
        )

    def _build_result(
        self, tool: ToolDefinition, raw_result: Any, fields: list[str] | None
    ) -> types.CallToolResult:
        if tool.output_schema is None:
            text = EMPTY_RESULT_TEXT if raw_result is None else json.dumps(raw_result)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=self._response_filter.redact(text))]
            )
        structured = {WRAPPED_RESULT_KEY: raw_result} if tool.is_result_wrapped else raw_result
        return build_structured_result(
            self._response_filter.apply(structured, fields, tool.is_result_wrapped)
        )
