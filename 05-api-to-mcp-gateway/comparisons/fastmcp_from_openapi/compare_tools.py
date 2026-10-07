"""Builds MCP tools from the orders OpenAPI document with ``FastMCP.from_openapi`` and records
how they differ from the phase 5 gateway's tools. Needs the orders backend on localhost:8001.

Run: ``python compare_tools.py`` (in this folder's own venv; fastmcp pins a newer mcp SDK).
"""

import asyncio
import json
import os
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx2
from fastmcp import Client, FastMCP

PHASE_DIRECTORY = Path(__file__).resolve().parents[2]
ORDERS_SPEC_FILE = PHASE_DIRECTORY / "tests" / "fixtures" / "orders_openapi.json"
GATEWAY_TOOLS_FILE = PHASE_DIRECTORY / "tests" / "fixtures" / "expected_orders_tools.json"
REPORT_FILE = PHASE_DIRECTORY / "results" / "comparison" / "fastmcp_from_openapi.md"
ORDERS_URL = os.environ.get("COMPARE_ORDERS_URL", "http://localhost:8001")


def describe_result(result: Any) -> str:
    structured = result.structured_content
    text = " ".join(getattr(block, "text", "") for block in result.content)
    return json.dumps({"is_error": result.is_error, "structured": structured, "text": text[:200]})


async def collect_fastmcp_behaviour() -> dict[str, Any]:
    spec = json.loads(ORDERS_SPEC_FILE.read_text(encoding="utf-8"))
    server = FastMCP.from_openapi(spec, client=httpx2.AsyncClient(base_url=ORDERS_URL))
    async with Client(server) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        templates = await client.list_resource_templates()
        tool_names = {tool.name for tool in tools}
        get_order_name = next(name for name in tool_names if "getOrder" in name)
        found = await client.call_tool(get_order_name, {"order_id": 1}, raise_on_error=False)
        missing = await client.call_tool(get_order_name, {"order_id": 999}, raise_on_error=False)
    return {
        "tools": {
            tool.name: {
                "description": (tool.description or "")[:80],
                "input_properties": sorted(tool.input_schema.get("properties", {})),
                "has_output_schema": tool.output_schema is not None,
            }
            for tool in tools
        },
        "resource_count": len(resources) + len(templates),
        "found": describe_result(found),
        "missing": describe_result(missing),
    }


def build_report(fastmcp_behaviour: dict[str, Any]) -> str:
    gateway_tools = json.loads(GATEWAY_TOOLS_FILE.read_text(encoding="utf-8"))
    tool_rows = "\n".join(
        f"| `{name}` | {', '.join(details['input_properties'])} | {details['has_output_schema']} |"
        for name, details in sorted(fastmcp_behaviour["tools"].items())
    )
    gateway_rows = "\n".join(
        f"| `{tool['name']}` | {', '.join(sorted(tool['input_schema']['properties']))} | "
        f"{tool['output_schema'] is not None} |"
        for tool in gateway_tools
    )
    return (
        "# FastMCP.from_openapi vs the phase 5 gateway\n\n"
        f"fastmcp {version('fastmcp')} on mcp {version('mcp')}; same orders OpenAPI document.\n\n"
        "## FastMCP.from_openapi tools\n\n| Tool | Arguments | Output schema |\n|---|---|---|\n"
        f"{tool_rows}\n\nResources / templates generated: {fastmcp_behaviour['resource_count']}\n\n"
        "## Gateway tools\n\n| Tool | Arguments | Output schema |\n|---|---|---|\n"
        f"{gateway_rows}\n\n"
        "## Calls (FastMCP.from_openapi)\n\n"
        f"- getOrder(1): `{fastmcp_behaviour['found']}`\n"
        f"- getOrder(999): `{fastmcp_behaviour['missing']}`\n"
    )


def main() -> None:
    report = build_report(asyncio.run(collect_fastmcp_behaviour()))
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
