from mcpharness.raw_protocol import (
    SseEventAccumulator,
    build_mcp_headers,
    build_tool_call_request,
    extract_jsonrpc_messages,
    find_response,
    parse_sse_events,
)

SSE_BODY = (
    "id: priming-1\n"
    "data: \n"
    "\n"
    "event: message\n"
    "id: event-2\n"
    'data: {"jsonrpc": "2.0", "method": "notifications/progress",\n'
    'data:  "params": {"progress": 1}}\n'
    "\n"
    "id: event-3\n"
    'data: {"jsonrpc": "2.0", "id": 7, "result": {}}\n'
    "\n"
)


def test_parses_events_with_ids_and_multi_line_data() -> None:
    parsed_events = parse_sse_events(SSE_BODY)

    assert [event.event_id for event in parsed_events] == ["priming-1", "event-2", "event-3"]
    assert parsed_events[0].jsonrpc_message() is None
    assert parsed_events[1].jsonrpc_message()["params"] == {"progress": 1}


def test_accumulator_ignores_comment_only_blocks() -> None:
    accumulator = SseEventAccumulator()

    assert accumulator.feed_line(": keep-alive") is None
    assert accumulator.feed_line("") is None


def test_extracts_messages_from_sse_and_json_bodies() -> None:
    from_sse = extract_jsonrpc_messages("text/event-stream; charset=utf-8", SSE_BODY)
    from_json = extract_jsonrpc_messages("application/json", '{"jsonrpc": "2.0", "id": 1}')
    from_empty = extract_jsonrpc_messages("application/json", "")

    assert len(from_sse) == 2
    assert find_response(from_sse, 7) == {"jsonrpc": "2.0", "id": 7, "result": {}}
    assert from_json == [{"jsonrpc": "2.0", "id": 1}]
    assert from_empty == []


def test_tool_call_request_carries_progress_token_only_when_given() -> None:
    with_token = build_tool_call_request("run_slow_job", {"seconds": 2}, 3, progress_token="t")
    without_token = build_tool_call_request("get_replica_id", {}, 4)

    assert with_token["params"]["_meta"] == {"progressToken": "t"}
    assert "_meta" not in without_token["params"]


def test_headers_include_session_and_version_only_when_known() -> None:
    assert "mcp-session-id" not in build_mcp_headers()
    assert build_mcp_headers("abc", "2025-11-25")["mcp-session-id"] == "abc"
