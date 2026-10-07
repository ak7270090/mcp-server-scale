"""Hand-built JSON-RPC messages and SSE parsing, for checks the SDK client hides from us."""

import json
from dataclasses import dataclass, field
from typing import Any

from mcpharness.constants import (
    ACCEPT_HEADER_VALUE,
    HARNESS_CLIENT_NAME,
    HARNESS_CLIENT_VERSION,
    JSON_CONTENT_TYPE,
    JSONRPC_VERSION,
    METHOD_INITIALIZE,
    METHOD_INITIALIZED,
    METHOD_TOOLS_CALL,
    PROTOCOL_VERSION_HEADER,
    SESSION_ID_HEADER,
    SSE_CONTENT_TYPE,
)


@dataclass
class SseEvent:
    event_id: str | None = None
    data_lines: list[str] = field(default_factory=list)

    @property
    def data(self) -> str:
        return "\n".join(self.data_lines)

    def jsonrpc_message(self) -> dict[str, Any] | None:
        """The JSON-RPC message in this event, or None for priming events with no data."""
        return json.loads(self.data) if self.data.strip() else None


class SseEventAccumulator:
    """Turns SSE lines into events; an event is complete at the first blank line."""

    def __init__(self) -> None:
        self._pending_event = SseEvent()

    def feed_line(self, line: str) -> SseEvent | None:
        if line == "":
            return self._complete_pending_event()
        field_name, _, field_value = line.partition(":")
        field_value = field_value.removeprefix(" ")
        if field_name == "id":
            self._pending_event.event_id = field_value
        elif field_name == "data":
            self._pending_event.data_lines.append(field_value)
        return None

    def _complete_pending_event(self) -> SseEvent | None:
        completed_event = self._pending_event
        self._pending_event = SseEvent()
        if completed_event.event_id is None and not completed_event.data_lines:
            return None
        return completed_event


def parse_sse_events(body: str) -> list[SseEvent]:
    accumulator = SseEventAccumulator()
    parsed_events = []
    for line in [*body.splitlines(), ""]:
        completed_event = accumulator.feed_line(line)
        if completed_event is not None:
            parsed_events.append(completed_event)
    return parsed_events


def extract_jsonrpc_messages(content_type: str, body: str) -> list[dict[str, Any]]:
    """All JSON-RPC messages in an HTTP response body, whether it is plain JSON or SSE."""
    if content_type.startswith(SSE_CONTENT_TYPE):
        messages = [event.jsonrpc_message() for event in parse_sse_events(body)]
        return [message for message in messages if message is not None]
    if content_type.startswith(JSON_CONTENT_TYPE) and body.strip():
        return [json.loads(body)]
    return []


def find_response(messages: list[dict[str, Any]], request_id: int) -> dict[str, Any] | None:
    return next((message for message in messages if message.get("id") == request_id), None)


def build_request(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method, "params": params}


def build_notification(method: str) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "method": method}


def build_initialize_request(request_id: int, protocol_version: str) -> dict[str, Any]:
    params = {
        "protocolVersion": protocol_version,
        "capabilities": {},
        "clientInfo": {"name": HARNESS_CLIENT_NAME, "version": HARNESS_CLIENT_VERSION},
    }
    return build_request(METHOD_INITIALIZE, params, request_id)


def build_initialized_notification() -> dict[str, Any]:
    return build_notification(METHOD_INITIALIZED)


def build_tool_call_request(
    tool_name: str,
    arguments: dict[str, Any],
    request_id: int,
    progress_token: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": tool_name, "arguments": arguments}
    if progress_token is not None:
        params["_meta"] = {"progressToken": progress_token}
    return build_request(METHOD_TOOLS_CALL, params, request_id)


def build_mcp_headers(
    session_id: str | None = None, protocol_version: str | None = None
) -> dict[str, str]:
    headers = {"Accept": ACCEPT_HEADER_VALUE, "Content-Type": JSON_CONTENT_TYPE}
    if session_id is not None:
        headers[SESSION_ID_HEADER] = session_id
    if protocol_version is not None:
        headers[PROTOCOL_VERSION_HEADER] = protocol_version
    return headers
