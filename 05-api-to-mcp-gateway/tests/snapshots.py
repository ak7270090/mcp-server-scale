"""Golden-file helpers: ``UPDATE_SNAPSHOTS=1 pytest`` rewrites the expected files."""

import json
import os
from pathlib import Path
from typing import Any

from apigateway.tool_definitions import RestRoute, ToolDefinition

FIXTURES_DIRECTORY = Path(__file__).parent / "fixtures"


def summarize_tool(tool: ToolDefinition) -> dict[str, Any]:
    if isinstance(tool.route, RestRoute):
        route = {
            "kind": "rest",
            "method": tool.route.method,
            "path": tool.route.path_template,
            "bindings": {
                name: [binding.location.value, binding.wire_name]
                for name, binding in tool.route.argument_bindings.items()
            },
            "result_wrapped": tool.route.is_result_wrapped,
        }
    else:
        route = {
            "kind": "grpc",
            "service": tool.route.service_full_name,
            "method": tool.route.method_name,
            "server_streaming": tool.route.is_server_streaming,
        }
    return {
        "name": tool.name,
        "description": tool.description,
        "read_only": tool.is_read_only,
        "destructive": tool.is_destructive,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "route": route,
    }


def assert_matches_snapshot(tools: list[ToolDefinition], snapshot_name: str) -> None:
    summaries = [summarize_tool(tool) for tool in sorted(tools, key=lambda tool: tool.name)]
    snapshot_path = FIXTURES_DIRECTORY / snapshot_name
    if os.environ.get("UPDATE_SNAPSHOTS"):
        snapshot_path.write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
    assert summaries == json.loads(snapshot_path.read_text(encoding="utf-8"))
