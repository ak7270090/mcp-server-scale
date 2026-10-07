"""Discovers the tools a backend offers: OpenAPI document for REST, server reflection for gRPC."""

import anyio
import httpx

from apigateway.config import GatewaySettings
from apigateway.config_files import RestServiceSource, ServiceSource
from apigateway.grpc_tool_builder import GrpcToolBuilder, load_service_descriptors
from apigateway.openapi_tool_builder import OpenApiToolBuilder
from apigateway.tool_definitions import ToolDefinition


class ServiceCrawler:
    def __init__(self, settings: GatewaySettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client

    async def discover(self, source: ServiceSource) -> list[ToolDefinition]:
        if isinstance(source, RestServiceSource):
            response = await self._http_client.get(source.openapi_url)
            response.raise_for_status()
            return OpenApiToolBuilder(
                source, response.json(), self._settings.max_schema_depth
            ).build_tools()
        services, descriptor_pool = await anyio.to_thread.run_sync(
            load_service_descriptors, source.target, self._settings.grpc_timeout_seconds
        )
        return GrpcToolBuilder(
            source, services, descriptor_pool, self._settings.max_schema_depth
        ).build_tools()
