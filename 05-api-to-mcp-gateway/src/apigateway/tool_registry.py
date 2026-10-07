"""Control plane: discovered tools, curation (disabled by default) and periodic reload."""

import dataclasses
import logging
from typing import Any, Protocol

import anyio

from apigateway.config import GatewaySettings
from apigateway.config_files import (
    ServiceSource,
    ToolOverride,
    load_services_file,
    load_tool_overrides,
)
from apigateway.tool_definitions import ToolDefinition

logger = logging.getLogger(__name__)


class ToolCrawler(Protocol):
    async def discover(self, source: ServiceSource) -> list[ToolDefinition]: ...


class ToolRegistry:
    """Discovery doesn't mean exposure: only tools enabled in the overrides file are served."""

    def __init__(self, settings: GatewaySettings, crawler: ToolCrawler) -> None:
        self._settings = settings
        self._crawler = crawler
        self._tools_by_service: dict[str, list[ToolDefinition]] = {}
        self._overrides: dict[str, ToolOverride] = {}
        self._enabled_tools: dict[str, ToolDefinition] = {}

    async def refresh(self) -> None:
        """Re-crawl every service and re-read the overrides; a failing service keeps its tools."""
        sources = load_services_file(self._settings.services_file)
        for source in sources:
            try:
                self._tools_by_service[source.name] = await self._crawler.discover(source)
            except Exception as error:
                known_count = len(self._tools_by_service.get(source.name, []))
                logger.warning(
                    "discovery failed for %s (%s); keeping %d known tools",
                    source.name,
                    error,
                    known_count,
                )
        configured_names = {source.name for source in sources}
        self._tools_by_service = {
            name: tools
            for name, tools in self._tools_by_service.items()
            if name in configured_names
        }
        try:
            self._overrides = load_tool_overrides(self._settings.overrides_file)
        except Exception as error:
            logger.warning("overrides file unreadable (%s); keeping previous overrides", error)
        self._enabled_tools = self._apply_overrides()

    def enabled_tools(self) -> list[ToolDefinition]:
        return sorted(self._enabled_tools.values(), key=lambda tool: tool.name)

    def find_enabled_tool(self, name: str) -> ToolDefinition | None:
        return self._enabled_tools.get(name)

    def describe_discovered_tools(self) -> list[dict[str, Any]]:
        """Every discovered tool with its curation state, for the ``/registry`` endpoint."""
        return [
            {
                "name": tool.name,
                "service": tool.service_name,
                "enabled": tool.name in self._enabled_tools,
                "read_only": tool.is_read_only,
                "description": self._enabled_tools.get(tool.name, tool).description,
            }
            for tools in self._tools_by_service.values()
            for tool in sorted(tools, key=lambda tool: tool.name)
        ]

    def _apply_overrides(self) -> dict[str, ToolDefinition]:
        enabled_tools = {}
        for tools in self._tools_by_service.values():
            for tool in tools:
                override = self._overrides.get(tool.name)
                if override is None or not override.enabled:
                    continue
                if override.description:
                    tool = dataclasses.replace(tool, description=override.description)
                enabled_tools[tool.name] = tool
        return enabled_tools


class RegistryRefresher:
    def __init__(self, registry: ToolRegistry, interval_seconds: float) -> None:
        self._registry = registry
        self._interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        while True:
            await anyio.sleep(self._interval_seconds)
            await self._registry.refresh()
