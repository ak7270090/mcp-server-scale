"""Minimal synchronous MCP client on Locust's HTTP session, so requests land in Locust stats."""

import itertools
from collections.abc import Mapping
from typing import Any

from locust.clients import HttpSession

from mcpharness.constants import (
    DEFAULT_PROTOCOL_VERSION,
    METHOD_TOOLS_CALL,
    SESSION_ID_HEADER,
    STRUCTURED_RESULT_KEY,
)
from mcpharness.raw_protocol import (
    build_initialize_request,
    build_initialized_notification,
    build_mcp_headers,
    build_tool_call_request,
    extract_jsonrpc_messages,
    find_response,
)


class McpRequestFailedError(RuntimeError):
    """An MCP request returned no response, a JSON-RPC error, or a tool error."""


class LocustMcpSession:
    """One MCP session per Locust user: initialize once, call tools, delete on stop."""

    def __init__(self, http_session: HttpSession, mcp_path: str) -> None:
        self._http_session = http_session
        self._mcp_path = mcp_path
        self._request_ids = itertools.count(1)
        self.session_id: str | None = None
        self.protocol_version: str | None = None

    def initialize(self) -> None:
        request_id = next(self._request_ids)
        response_message, response_headers = self._post_request(
            build_initialize_request(request_id, DEFAULT_PROTOCOL_VERSION),
            request_id,
            request_name="initialize",
        )
        self.session_id = response_headers.get(SESSION_ID_HEADER)
        self.protocol_version = response_message["result"]["protocolVersion"]
        self._http_session.post(
            self._mcp_path,
            json=build_initialized_notification(),
            headers=build_mcp_headers(self.session_id, self.protocol_version),
            name="notifications/initialized",
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        request_id = next(self._request_ids)
        response_message, _ = self._post_request(
            build_tool_call_request(tool_name, arguments or {}, request_id),
            request_id,
            request_name=f"{METHOD_TOOLS_CALL} {tool_name}",
        )
        structured = response_message["result"].get("structuredContent") or {}
        return structured.get(STRUCTURED_RESULT_KEY, structured)

    def close(self) -> None:
        if self.session_id is None:
            return
        self._http_session.delete(
            self._mcp_path,
            headers=build_mcp_headers(self.session_id, self.protocol_version),
            name="DELETE session",
        )
        self.session_id = None

    def _post_request(
        self, payload: dict[str, Any], request_id: int, request_name: str
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        with self._http_session.post(
            self._mcp_path,
            json=payload,
            headers=build_mcp_headers(self.session_id, self.protocol_version),
            name=request_name,
            catch_response=True,
        ) as response:
            messages = extract_jsonrpc_messages(
                response.headers.get("content-type", ""), response.text
            )
            response_message = find_response(messages, request_id)
            failure_reason = self._find_failure_reason(response.status_code, response_message)
            if failure_reason is not None:
                response.failure(failure_reason)
                raise McpRequestFailedError(failure_reason)
            return response_message, response.headers

    @staticmethod
    def _find_failure_reason(
        status_code: int, response_message: dict[str, Any] | None
    ) -> str | None:
        if status_code != 200:
            return f"HTTP {status_code}"
        if response_message is None:
            return "no JSON-RPC response in body"
        if "error" in response_message:
            return f"JSON-RPC error {response_message['error'].get('code')}"
        if response_message.get("result", {}).get("isError"):
            return "tool returned isError"
        return None
