import json
from typing import Any

import grpc
import httpx
import pytest
import respx
from google.protobuf.descriptor_pool import DescriptorPool

from apigateway.config import GatewaySettings
from apigateway.config_files import GrpcServiceSource
from apigateway.error_mapping import BackendCallError, map_grpc_failure, map_http_failure
from apigateway.grpc_invoker import GrpcInvoker
from apigateway.rest_invoker import RestInvoker
from apigateway.service_crawler import ServiceCrawler
from apigateway.tool_definitions import ToolDefinition
from tests.conftest import (
    ORDERS_BASE_URL,
    ORDERS_SOURCE,
    build_inventory_tools,
    build_orders_tools,
)
from tests.fake_inventory import LARGE_STOCK, MISSING_SKU, WATCH_UPDATE_COUNT

pytestmark = pytest.mark.anyio

PASSTHROUGH = {"authorization": "Bearer t0k3n", "traceparent": "00-abc-def-01"}


class ProgressRecorder:
    def __init__(self) -> None:
        self.reports: list[tuple[float, str | None]] = []

    async def report(self, progress: float, total: float | None, message: str | None) -> None:
        self.reports.append((progress, message))


def tools_by_name(tools: list[ToolDefinition]) -> dict[str, ToolDefinition]:
    return {tool.name: tool for tool in tools}


@respx.mock
async def test_rest_call_places_arguments_and_forwards_headers(
    orders_openapi_spec: dict[str, Any],
) -> None:
    route = respx.post(f"{ORDERS_BASE_URL}/orders").mock(
        return_value=httpx.Response(201, json={"id": 9})
    )
    tool = tools_by_name(build_orders_tools(orders_openapi_spec))["orders_create_order"]
    arguments = {
        "customer_email": "a@b.co",
        "customer_phone": "+1 555 0100",
        "items": [{"sku": "SKU-001", "quantity": 1}],
    }

    async with httpx.AsyncClient() as client:
        result = await RestInvoker(client).invoke(tool.route, arguments, PASSTHROUGH)

    sent = route.calls.last.request
    assert result == {"id": 9}
    assert json.loads(sent.content) == arguments
    assert sent.headers["authorization"] == "Bearer t0k3n"
    assert sent.headers["traceparent"] == "00-abc-def-01"


@respx.mock
async def test_rest_call_fills_path_and_query(orders_openapi_spec: dict[str, Any]) -> None:
    get_route = respx.get(f"{ORDERS_BASE_URL}/orders/a%2Fb").mock(
        return_value=httpx.Response(200, json={})
    )
    list_route = respx.get(f"{ORDERS_BASE_URL}/orders").mock(
        return_value=httpx.Response(200, json=[])
    )
    tools = tools_by_name(build_orders_tools(orders_openapi_spec))

    async with httpx.AsyncClient() as client:
        invoker = RestInvoker(client)
        await invoker.invoke(tools["orders_get_order"].route, {"order_id": "a/b"}, {})
        await invoker.invoke(
            tools["orders_list_orders"].route, {"status": "shipped", "limit": 2}, {}
        )

    assert get_route.called
    assert dict(list_route.calls.last.request.url.params) == {"status": "shipped", "limit": "2"}


@pytest.mark.parametrize(("status_code", "is_retryable"), [(404, False), (409, False), (503, True)])
@respx.mock
async def test_rest_error_status_becomes_backend_failure(
    orders_openapi_spec: dict[str, Any], status_code: int, is_retryable: bool
) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders/1").mock(
        return_value=httpx.Response(status_code, json={"detail": "nope"})
    )
    tool = tools_by_name(build_orders_tools(orders_openapi_spec))["orders_get_order"]

    async with httpx.AsyncClient() as client:
        with pytest.raises(BackendCallError) as error:
            await RestInvoker(client).invoke(tool.route, {"order_id": 1}, {})

    assert f"HTTP {status_code}: nope" in error.value.failure.message
    assert error.value.failure.is_retryable is is_retryable


@respx.mock
async def test_rest_connection_failure_is_retryable(orders_openapi_spec: dict[str, Any]) -> None:
    respx.get(f"{ORDERS_BASE_URL}/orders/1").mock(side_effect=httpx.ConnectError("refused"))
    tool = tools_by_name(build_orders_tools(orders_openapi_spec))["orders_get_order"]

    async with httpx.AsyncClient() as client:
        with pytest.raises(BackendCallError) as error:
            await RestInvoker(client).invoke(tool.route, {"order_id": 1}, {})

    assert error.value.failure.is_retryable


async def test_grpc_unary_call_maps_json_both_ways(
    inventory_descriptor_pool: DescriptorPool, fake_inventory
) -> None:
    service, target = fake_inventory
    tools = tools_by_name(build_inventory_tools(inventory_descriptor_pool, target))
    invoker = GrpcInvoker(GatewaySettings())

    result = await invoker.invoke(
        tools["inventory_reserve_stock"].route,
        {"sku": "SKU-001", "quantity": 3, "holdMinutes": 10, "labels": {"team": "a"}},
        PASSTHROUGH,
        ProgressRecorder(),
    )
    stock = await invoker.invoke(
        tools["inventory_get_stock"].route, {"sku": "SKU-001"}, {}, ProgressRecorder()
    )
    await invoker.close()

    method_name, decoded_request = service.received_requests[0]
    assert method_name == "ReserveStock"
    assert decoded_request.hold_minutes == 10
    assert dict(decoded_request.labels) == {"team": "a"}
    assert service.received_metadata[0]["authorization"] == "Bearer t0k3n"
    assert result == {"reservationId": "r-1", "sku": "SKU-001", "quantity": 3, "remaining": "7"}
    assert stock["available"] == str(LARGE_STOCK)
    assert stock["status"] == "IN_STOCK"
    assert stock["updatedAt"] == "2023-11-14T22:13:20Z"


async def test_grpc_stream_reports_progress_and_returns_last_update(
    inventory_descriptor_pool: DescriptorPool, fake_inventory
) -> None:
    _, target = fake_inventory
    tool = tools_by_name(build_inventory_tools(inventory_descriptor_pool, target))[
        "inventory_watch_stock"
    ]
    progress = ProgressRecorder()
    invoker = GrpcInvoker(GatewaySettings())

    result = await invoker.invoke(tool.route, {"sku": "SKU-001", "updates": 3}, {}, progress)
    await invoker.close()

    assert [value for value, _ in progress.reports] == list(range(1, WATCH_UPDATE_COUNT + 1))
    assert json.loads(progress.reports[-1][1]) == result
    assert result["sku"] == "SKU-001"


async def test_grpc_status_becomes_backend_failure(
    inventory_descriptor_pool: DescriptorPool, fake_inventory
) -> None:
    _, target = fake_inventory
    tool = tools_by_name(build_inventory_tools(inventory_descriptor_pool, target))[
        "inventory_get_stock"
    ]
    invoker = GrpcInvoker(GatewaySettings())

    with pytest.raises(BackendCallError) as error:
        await invoker.invoke(tool.route, {"sku": MISSING_SKU}, {}, ProgressRecorder())
    await invoker.close()

    assert "gRPC NOT_FOUND" in error.value.failure.message
    assert not error.value.failure.is_retryable


async def test_grpc_rejects_arguments_that_do_not_parse(
    inventory_descriptor_pool: DescriptorPool,
) -> None:
    tool = tools_by_name(build_inventory_tools(inventory_descriptor_pool))["inventory_get_stock"]

    with pytest.raises(BackendCallError, match="do not match inventory.v1.GetStockRequest"):
        await GrpcInvoker(GatewaySettings()).invoke(
            tool.route, {"sku": 5, "nope": 1}, {}, ProgressRecorder()
        )


@respx.mock
async def test_crawler_reads_openapi_document(orders_openapi_spec: dict[str, Any]) -> None:
    respx.get(ORDERS_SOURCE.openapi_url).mock(
        return_value=httpx.Response(200, json=orders_openapi_spec)
    )

    async with httpx.AsyncClient() as client:
        tools = await ServiceCrawler(GatewaySettings(), client).discover(ORDERS_SOURCE)

    assert "orders_get_order" in {tool.name for tool in tools}


async def test_crawler_discovers_grpc_service_through_reflection(fake_inventory) -> None:
    _, target = fake_inventory
    source = GrpcServiceSource(kind="grpc", name="inventory", target=target)

    async with httpx.AsyncClient() as client:
        tools = await ServiceCrawler(GatewaySettings(), client).discover(source)

    assert {tool.name for tool in tools} == {
        "inventory_get_stock",
        "inventory_reserve_stock",
        "inventory_watch_stock",
    }
    invoker = GrpcInvoker(GatewaySettings())
    reflected_get_stock = tools_by_name(tools)["inventory_get_stock"]
    result = await invoker.invoke(
        reflected_get_stock.route, {"sku": "SKU-002"}, {}, ProgressRecorder()
    )
    await invoker.close()
    assert result["warehouse"]["city"] == "Amsterdam"


def test_grpc_codes_classified_for_retry() -> None:
    assert map_grpc_failure(grpc.StatusCode.UNAVAILABLE, "down").is_retryable
    assert not map_grpc_failure(grpc.StatusCode.FAILED_PRECONDITION, "no stock").is_retryable
    assert map_http_failure(422, '{"detail": [{"loc": ["x"]}]}').message.endswith(
        '[{"loc": ["x"]}]'
    )
    assert map_http_failure(500, "plain text").message == "backend returned HTTP 500: plain text"
