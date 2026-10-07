from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from google.protobuf.descriptor_pool import DescriptorPool
from mcp import ClientSession, types
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.applications import Starlette
from starlette.testclient import TestClient

from apigateway.app import create_gateway_app
from apigateway.config import GatewaySettings
from apigateway.config_files import ServiceSource
from apigateway.discovery_tools import DiscoveryTools
from apigateway.grpc_invoker import GrpcInvoker
from apigateway.mcp_server import GatewayMcpServer
from apigateway.response_filters import ResponseFilter
from apigateway.rest_facade import RestFacade, build_facade_openapi
from apigateway.rest_invoker import RestInvoker
from apigateway.tool_definitions import ToolDefinition
from apigateway.tool_registry import ToolRegistry
from apigateway.tool_router import ToolRouter
from tests.conftest import (
    ALL_ENABLED_OVERRIDES,
    ORDERS_BASE_URL,
    build_inventory_tools,
    build_orders_tools,
    write_config_files,
)
from tests.fake_inventory import FLAKY_SKU, WATCH_UPDATE_COUNT

pytestmark = pytest.mark.anyio

SEEDED_ORDER = {
    "id": 1,
    "status": "pending",
    "customer_email": "ana@example.com",
    "customer_phone": "+1 415 555 0100",
    "items": [{"sku": "SKU-001", "quantity": 2}],
    "total_cents": 3998,
    "created_at": "2026-10-08T10:00:00Z",
}


class FixedToolsCrawler:
    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools = tools

    async def discover(self, source: ServiceSource) -> list[ToolDefinition]:
        return [tool for tool in self._tools if tool.service_name == source.name]


class InMemoryUpstream:
    """The facade's MCP upstream, connected in memory to a gateway MCP server."""

    def __init__(self, gateway: GatewayMcpServer) -> None:
        self._gateway = gateway

    @asynccontextmanager
    async def open_session(self, headers: dict[str, str]) -> AsyncIterator[ClientSession]:
        async with create_connected_server_and_client_session(self._gateway.server) as session:
            yield session


class ProgressRecorder:
    def __init__(self) -> None:
        self.progress_values: list[float] = []

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress_values.append(progress)


async def build_gateway(
    tmp_path: Path,
    orders_spec: dict[str, Any],
    descriptor_pool: DescriptorPool,
    inventory_target: str,
    http_client: httpx.AsyncClient,
    is_discovery_mode: bool = False,
) -> GatewayMcpServer:
    services = [
        {
            "kind": "rest",
            "name": "orders",
            "base_url": ORDERS_BASE_URL,
            "openapi_url": f"{ORDERS_BASE_URL}/openapi.json",
        },
        {"kind": "grpc", "name": "inventory", "target": inventory_target},
    ]
    settings = write_config_files(tmp_path, ALL_ENABLED_OVERRIDES, services).model_copy(
        update={"is_discovery_mode": is_discovery_mode}
    )
    tools = build_orders_tools(orders_spec) + build_inventory_tools(
        descriptor_pool, inventory_target
    )
    registry = ToolRegistry(settings, FixedToolsCrawler(tools))
    await registry.refresh()
    router = ToolRouter(
        settings,
        registry,
        RestInvoker(http_client),
        GrpcInvoker(settings),
        ResponseFilter(settings.redaction_patterns),
    )
    return GatewayMcpServer(settings, registry, router, DiscoveryTools(settings, registry, router))


@pytest.fixture
async def gateway(
    tmp_path: Path,
    orders_openapi_spec: dict[str, Any],
    inventory_descriptor_pool: DescriptorPool,
    fake_inventory,
) -> AsyncIterator[GatewayMcpServer]:
    _, target = fake_inventory
    async with httpx.AsyncClient() as http_client:
        yield await build_gateway(
            tmp_path, orders_openapi_spec, inventory_descriptor_pool, target, http_client
        )


@pytest.fixture
async def discovery_gateway(
    tmp_path: Path,
    orders_openapi_spec: dict[str, Any],
    inventory_descriptor_pool: DescriptorPool,
    fake_inventory,
) -> AsyncIterator[GatewayMcpServer]:
    _, target = fake_inventory
    async with httpx.AsyncClient() as http_client:
        yield await build_gateway(
            tmp_path,
            orders_openapi_spec,
            inventory_descriptor_pool,
            target,
            http_client,
            is_discovery_mode=True,
        )


async def test_lists_only_enabled_tools_with_annotations(gateway: GatewayMcpServer) -> None:
    async with create_connected_server_and_client_session(gateway.server) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    assert set(tools) == set(ALL_ENABLED_OVERRIDES)
    assert tools["orders_get_order"].description == "Look up one order."
    assert tools["orders_get_order"].annotations.readOnlyHint
    assert not tools["orders_create_order"].annotations.readOnlyHint


@respx.mock
async def test_projects_and_redacts_rest_result(gateway: GatewayMcpServer) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders/1").mock(
        return_value=httpx.Response(200, json=SEEDED_ORDER)
    )

    async with create_connected_server_and_client_session(gateway.server) as session:
        full = await session.call_tool("orders_get_order", {"order_id": 1})
        projected = await session.call_tool(
            "orders_get_order", {"order_id": 1, "fields": ["id", "customer_email"]}
        )

    assert full.structuredContent["customer_phone"] == "[REDACTED]"
    assert full.structuredContent["total_cents"] == 3998
    assert projected.structuredContent == {"id": 1, "customer_email": "[REDACTED]"}


@respx.mock
async def test_list_result_is_wrapped_and_projected_per_item(gateway: GatewayMcpServer) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders").mock(
        return_value=httpx.Response(200, json=[SEEDED_ORDER, {**SEEDED_ORDER, "id": 2}])
    )

    async with create_connected_server_and_client_session(gateway.server) as session:
        result = await session.call_tool("orders_list_orders", {"fields": ["id"]})

    assert result.structuredContent == {"result": [{"id": 1}, {"id": 2}]}


@respx.mock
async def test_backend_errors_become_tool_errors(gateway: GatewayMcpServer) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders/99").mock(
        return_value=httpx.Response(404, json={"detail": "order 99 not found"})
    )

    async with create_connected_server_and_client_session(gateway.server) as session:
        missing = await session.call_tool("orders_get_order", {"order_id": 99})
        invalid = await session.call_tool("orders_get_order", {"order_id": "abc"})

    assert missing.isError
    assert missing.content[0].text == "backend returned HTTP 404: order 99 not found"
    assert invalid.isError
    assert invalid.content[0].text.startswith("invalid arguments")


async def test_unknown_tool_is_a_json_rpc_error(gateway: GatewayMcpServer) -> None:
    async with create_connected_server_and_client_session(gateway.server) as session:
        with pytest.raises(McpError) as error:
            await session.call_tool("orders_cancel_order", {"order_id": 1})

    assert error.value.error.code == types.INVALID_PARAMS


@respx.mock
async def test_read_only_tools_retry_temporary_failures(gateway: GatewayMcpServer) -> None:
    read_route = respx.get(f"{ORDERS_BASE_URL}/orders/1").mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, json={"id": 1})]
    )
    write_route = respx.post(f"{ORDERS_BASE_URL}/orders").mock(return_value=httpx.Response(503))
    order = {
        "customer_email": "a@b.co",
        "customer_phone": "x",
        "items": [{"sku": "A", "quantity": 1}],
    }

    async with create_connected_server_and_client_session(gateway.server) as session:
        read_result = await session.call_tool("orders_get_order", {"order_id": 1})
        write_result = await session.call_tool("orders_create_order", order)

    assert not read_result.isError
    assert read_route.call_count == 3
    assert write_result.isError
    assert "retrying may succeed" in write_result.content[0].text
    assert write_route.call_count == 1


async def test_grpc_tools_retry_stream_and_forward_progress(
    gateway: GatewayMcpServer, fake_inventory
) -> None:
    service, _ = fake_inventory
    recorder = ProgressRecorder()

    async with create_connected_server_and_client_session(gateway.server) as session:
        flaky = await session.call_tool("inventory_get_stock", {"sku": FLAKY_SKU})
        watched = await session.call_tool(
            "inventory_watch_stock",
            {"sku": "SKU-001", "updates": 3},
            progress_callback=recorder.record,
        )

    assert flaky.structuredContent["sku"] == FLAKY_SKU
    assert [name for name, _ in service.received_requests].count("GetStock") == 3
    assert recorder.progress_values == [float(step) for step in range(1, WATCH_UPDATE_COUNT + 1)]
    assert watched.structuredContent["warehouse"] == {"code": "AMS1", "city": "Amsterdam"}


async def test_discovery_mode_exposes_three_meta_tools(
    discovery_gateway: GatewayMcpServer,
) -> None:
    async with create_connected_server_and_client_session(discovery_gateway.server) as session:
        listed = [tool.name for tool in (await session.list_tools()).tools]
        found = await session.call_tool("search_tools", {"query": "stock"})
        schema = await session.call_tool("get_tool_schema", {"name": "inventory_get_stock"})
        invoked = await session.call_tool(
            "invoke_tool", {"name": "inventory_get_stock", "arguments": {"sku": "SKU-001"}}
        )
        unknown_inner = await session.call_tool("invoke_tool", {"name": "nope"})
        missing_schema = await session.call_tool("get_tool_schema", {"name": "nope"})
        bad_arguments = await session.call_tool("search_tools", {})
        with pytest.raises(McpError):
            await session.call_tool("inventory_get_stock", {"sku": "SKU-001"})

    found_names = [tool["name"] for tool in found.structuredContent["tools"]]
    assert listed == ["search_tools", "get_tool_schema", "invoke_tool"]
    assert {"inventory_get_stock", "inventory_watch_stock", "inventory_reserve_stock"} <= set(
        found_names
    )
    assert schema.structuredContent["inputSchema"]["properties"]["sku"] == {"type": "string"}
    assert invoked.structuredContent["sku"] == "SKU-001"
    assert unknown_inner.isError and missing_schema.isError and bad_arguments.isError


@respx.mock
async def test_rest_facade_mirrors_mcp_tools(gateway: GatewayMcpServer) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders/1").mock(
        return_value=httpx.Response(200, json=SEEDED_ORDER)
    )
    respx.get(f"{ORDERS_BASE_URL}/orders/99").mock(
        return_value=httpx.Response(404, json={"detail": "order 99 not found"})
    )
    facade_app = Starlette(routes=RestFacade(InMemoryUpstream(gateway)).routes())
    transport = httpx.ASGITransport(app=facade_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://facade") as client:
        listed = await client.get("/facade/tools")
        found = await client.post("/facade/tools/orders_get_order", json={"order_id": 1})
        missing = await client.post("/facade/tools/orders_get_order", json={"order_id": 99})
        unknown = await client.post("/facade/tools/no_such_tool", json={})
        not_object = await client.post("/facade/tools/orders_get_order", json=[1])
        not_json = await client.post("/facade/tools/orders_get_order", content=b"{")
        document = await client.get("/facade/openapi.json")

    assert {tool["name"] for tool in listed.json()["tools"]} == set(ALL_ENABLED_OVERRIDES)
    assert found.status_code == 200
    assert found.json()["result"]["customer_email"] == "[REDACTED]"
    assert (missing.status_code, missing.json()["error"]) == (
        422,
        "backend returned HTTP 404: order 99 not found",
    )
    assert unknown.status_code == 404
    assert not_object.status_code == 400
    assert not_json.status_code == 400
    assert "/facade/tools/orders_get_order" in document.json()["paths"]


@respx.mock
async def test_rest_facade_edge_cases_found_by_schemathesis(gateway: GatewayMcpServer) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders/1").mock(
        return_value=httpx.Response(200, json=SEEDED_ORDER)
    )
    facade_app = Starlette(routes=RestFacade(InMemoryUpstream(gateway)).routes())
    transport = httpx.ASGITransport(app=facade_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://facade") as client:
        invalid_utf8 = await client.post("/facade/tools/orders_get_order", content=b"\xff[")
        empty_projection = await client.post(
            "/facade/tools/orders_get_order", json={"order_id": 1, "fields": ["no_such_field"]}
        )

    assert invalid_utf8.status_code == 400
    assert empty_projection.json() == {"result": {}}


class BrokenUpstream:
    @asynccontextmanager
    async def open_session(self, headers: dict[str, str]) -> AsyncIterator[ClientSession]:
        raise ConnectionError("upstream down")
        yield


async def test_facade_reports_unavailable_upstream() -> None:
    facade_app = Starlette(routes=RestFacade(BrokenUpstream()).routes())
    transport = httpx.ASGITransport(app=facade_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://facade") as client:
        responses = [
            await client.get("/facade/tools"),
            await client.get("/facade/openapi.json"),
            await client.post("/facade/tools/x", json={}),
        ]

    assert [response.status_code for response in responses] == [502, 502, 502]


def test_facade_openapi_documents_each_tool() -> None:
    tool = types.Tool(
        name="orders_get_order",
        description="Look up one order.",
        inputSchema={"type": "object", "properties": {"order_id": {"type": "integer"}}},
        outputSchema={"type": "object", "properties": {"id": {"type": "integer"}}},
    )

    document = build_facade_openapi([tool])
    operation = document["paths"]["/facade/tools/orders_get_order"]["post"]

    assert operation["operationId"] == "orders_get_order"
    assert operation["requestBody"]["content"]["application/json"]["schema"] == tool.inputSchema
    result_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert result_schema["properties"]["result"] == tool.outputSchema
    assert set(operation["responses"]) == {"200", "400", "404", "422", "502"}


def test_app_serves_health_and_registry(
    tmp_path: Path, orders_openapi_spec: dict[str, Any]
) -> None:
    settings: GatewaySettings = write_config_files(
        tmp_path, {"orders_get_order": {"enabled": True}}
    )
    app = create_gateway_app(
        settings,
        crawler=FixedToolsCrawler(build_orders_tools(orders_openapi_spec)),
        upstream=BrokenUpstream(),
    )

    with TestClient(app) as client:
        health = client.get("/healthz")
        registry = client.get("/registry").json()["tools"]

    enabled_names = [tool["name"] for tool in registry if tool["enabled"]]
    assert health.json() == {"status": "ok"}
    assert len(registry) == 5
    assert enabled_names == ["orders_get_order"]
