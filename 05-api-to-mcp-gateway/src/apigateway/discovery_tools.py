"""Many-tools mode: three meta-tools let the model search, inspect and invoke any enabled tool."""

from typing import Any

import jsonschema
from mcp import types

from apigateway.config import GatewaySettings
from apigateway.constants import (
    DISCOVERY_INVOKE_TOOL,
    DISCOVERY_SCHEMA_TOOL,
    DISCOVERY_SEARCH_TOOL,
)
from apigateway.tool_registry import ToolRegistry
from apigateway.tool_router import (
    CallContext,
    ToolRouter,
    UnknownToolError,
    build_error_result,
    build_structured_result,
)

DISCOVERY_TOOLS = [
    types.Tool(
        name=DISCOVERY_SEARCH_TOOL,
        description="Find tools by keywords; returns names and descriptions.",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name=DISCOVERY_SCHEMA_TOOL,
        description="Return a tool's input and output JSON Schemas.",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name=DISCOVERY_INVOKE_TOOL,
        description="Call a tool by name with arguments matching its input schema.",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
]
DISCOVERY_TOOLS_BY_NAME = {tool.name: tool for tool in DISCOVERY_TOOLS}


class DiscoveryTools:
    def __init__(self, settings: GatewaySettings, registry: ToolRegistry, router: ToolRouter):
        self._settings = settings
        self._registry = registry
        self._router = router

    def list_mcp_tools(self) -> list[types.Tool]:
        return list(DISCOVERY_TOOLS)

    async def call_tool(
        self, name: str, arguments: dict[str, Any], call_context: CallContext
    ) -> types.CallToolResult:
        if name not in DISCOVERY_TOOLS_BY_NAME:
            raise UnknownToolError(name)
        try:
            jsonschema.validate(arguments, DISCOVERY_TOOLS_BY_NAME[name].inputSchema)
        except jsonschema.ValidationError as error:
            return build_error_result(f"invalid arguments: {error.message}")
        if name == DISCOVERY_SEARCH_TOOL:
            return self.search_tools(arguments["query"])
        if name == DISCOVERY_SCHEMA_TOOL:
            return self.get_tool_schema(arguments["name"])
        try:
            return await self._router.call_tool(
                arguments["name"], arguments.get("arguments", {}), call_context
            )
        except UnknownToolError:
            return build_error_result(f"no enabled tool named {arguments['name']!r}")

    def search_tools(self, query: str) -> types.CallToolResult:
        query_words = query.lower().split()
        scored_tools = []
        for tool in self._registry.enabled_tools():
            searchable_text = f"{tool.name.replace('_', ' ')} {tool.description}".lower()
            score = sum(word in searchable_text for word in query_words)
            if score:
                scored_tools.append((score, tool))
        scored_tools.sort(key=lambda scored: (-scored[0], scored[1].name))
        matches = [
            {"name": tool.name, "description": tool.description}
            for _, tool in scored_tools[: self._settings.discovery_result_limit]
        ]
        return build_structured_result({"tools": matches})

    def get_tool_schema(self, tool_name: str) -> types.CallToolResult:
        tool = self._registry.find_enabled_tool(tool_name)
        if tool is None:
            return build_error_result(f"no enabled tool named {tool_name!r}")
        return build_structured_result(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
                "outputSchema": tool.output_schema,
            }
        )
