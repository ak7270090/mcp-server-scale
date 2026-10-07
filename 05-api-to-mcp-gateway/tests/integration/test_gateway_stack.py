import time

import anyio
import httpx
import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from tests.integration.gateway_client import (
    GATEWAY_BASE_URL,
    OVERRIDES_FILE,
    PASSTHROUGH_HEADERS,
    RESULTS_DIRECTORY,
    open_gateway_session,
    run_schemathesis,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

CURATED_TOOLS = {
    "orders_get_order",
    "orders_list_orders",
    "orders_create_order",
    "orders_get_caller",
    "inventory_get_stock",
    "inventory_reserve_stock",
    "inventory_watch_stock",
}
RELOAD_TIMEOUT_SECONDS = 30
SCHEMATHESIS_MAX_EXAMPLES = 15


class ProgressRecorder:
    def __init__(self) -> None:
        self.progress_values: list[float] = []

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress_values.append(progress)


async def list_tool_names() -> set[str]:
    async with open_gateway_session() as session:
        return {tool.name for tool in (await session.list_tools()).tools}


async def wait_for_tool_names(predicate_name: str, should_exist: bool) -> float:
    """Poll the gateway (it re-reads overrides on a timer) until the tool appears or goes."""
    started_at = time.monotonic()
    for _ in range(RELOAD_TIMEOUT_SECONDS):
        if (predicate_name in await list_tool_names()) is should_exist:
            return time.monotonic() - started_at
        await anyio.sleep(1)
    raise TimeoutError(f"{predicate_name} never {'appeared' if should_exist else 'disappeared'}")


async def test_lists_only_curated_tools() -> None:
    assert await list_tool_names() == CURATED_TOOLS


async def test_rest_tool_redacts_projects_and_maps_errors() -> None:
    async with open_gateway_session() as session:
        full = await session.call_tool("orders_get_order", {"order_id": 1})
        projected = await session.call_tool(
            "orders_get_order", {"order_id": 1, "fields": ["id", "status", "total_cents"]}
        )
        missing = await session.call_tool("orders_get_order", {"order_id": 999})

    assert full.structuredContent["customer_email"] == "[REDACTED]"
    assert full.structuredContent["customer_phone"] == "[REDACTED]"
    assert projected.structuredContent == {"id": 1, "status": "pending", "total_cents": 3998}
    assert missing.isError
    assert missing.content[0].text == "backend returned HTTP 404: order 999 not found"


async def test_grpc_tools_translate_types_errors_and_streams() -> None:
    progress = ProgressRecorder()
    async with open_gateway_session() as session:
        stock = await session.call_tool("inventory_get_stock", {"sku": "SKU-002"})
        missing = await session.call_tool("inventory_get_stock", {"sku": "SKU-404"})
        too_many = await session.call_tool(
            "inventory_reserve_stock", {"sku": "SKU-003", "quantity": 1, "holdMinutes": 5}
        )
        watched = await session.call_tool(
            "inventory_watch_stock",
            {"sku": "SKU-001", "updates": 3, "intervalMs": 100},
            progress_callback=progress.record,
        )

    assert stock.structuredContent["available"] == "3"
    assert stock.structuredContent["status"] == "LOW_STOCK"
    assert stock.structuredContent["warehouse"]["city"] == "Bengaluru"
    assert "gRPC NOT_FOUND" in missing.content[0].text
    assert "gRPC FAILED_PRECONDITION" in too_many.content[0].text
    assert progress.progress_values == [1.0, 2.0, 3.0]
    assert watched.structuredContent["sku"] == "SKU-001"


async def test_authorization_and_traceparent_reach_the_backend() -> None:
    async with open_gateway_session(PASSTHROUGH_HEADERS) as session:
        via_mcp = await session.call_tool("orders_get_caller", {})
    async with httpx.AsyncClient(headers=PASSTHROUGH_HEADERS, timeout=60) as client:
        via_facade = await client.post(
            f"{GATEWAY_BASE_URL}/facade/tools/orders_get_caller", json={}
        )

    expected = {
        "authorization": PASSTHROUGH_HEADERS["Authorization"],
        "traceparent": PASSTHROUGH_HEADERS["traceparent"],
    }
    assert via_mcp.structuredContent == expected
    assert via_facade.json()["result"] == expected


async def test_disabled_tool_is_a_protocol_error() -> None:
    async with open_gateway_session() as session:
        with pytest.raises(McpError) as error:
            await session.call_tool("orders_cancel_order", {"order_id": 1})

    assert error.value.error.code == types.INVALID_PARAMS


async def test_enabling_a_tool_in_overrides_applies_without_restart() -> None:
    original_overrides = OVERRIDES_FILE.read_text(encoding="utf-8")
    enabled_overrides = original_overrides.replace(
        "  orders_cancel_order:\n    enabled: false", "  orders_cancel_order:\n    enabled: true"
    )
    assert enabled_overrides != original_overrides
    try:
        OVERRIDES_FILE.write_text(enabled_overrides, encoding="utf-8")
        seconds_to_appear = await wait_for_tool_names("orders_cancel_order", should_exist=True)
        async with open_gateway_session() as session:
            shipped = await session.call_tool("orders_cancel_order", {"order_id": 2})
    finally:
        OVERRIDES_FILE.write_text(original_overrides, encoding="utf-8")
    seconds_to_disappear = await wait_for_tool_names("orders_cancel_order", should_exist=False)
    async with httpx.AsyncClient(timeout=30) as client:
        registry = (await client.get(f"{GATEWAY_BASE_URL}/registry")).json()["tools"]

    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIRECTORY / "reload.md").write_text(
        "# Curation reload\n\n"
        f"orders_cancel_order appeared {seconds_to_appear:.1f} s after enabling, "
        f"disappeared {seconds_to_disappear:.1f} s after disabling (refresh interval 5 s).\n",
        encoding="utf-8",
    )
    assert shipped.isError and "HTTP 409" in shipped.content[0].text
    assert {tool["name"] for tool in registry if not tool["enabled"]} == {"orders_cancel_order"}


async def test_facade_returns_the_same_result_as_mcp() -> None:
    async with open_gateway_session() as session:
        via_mcp = await session.call_tool("inventory_get_stock", {"sku": "SKU-001"})
    async with httpx.AsyncClient(timeout=60) as client:
        via_facade = await client.post(
            f"{GATEWAY_BASE_URL}/facade/tools/inventory_get_stock", json={"sku": "SKU-001"}
        )

    facade_result = via_facade.json()["result"]
    assert set(facade_result) == set(via_mcp.structuredContent)
    assert facade_result["sku"] == via_mcp.structuredContent["sku"]


def test_facade_survives_schemathesis_fuzzing() -> None:
    report_directory = RESULTS_DIRECTORY / "schemathesis"
    completed = run_schemathesis(report_directory, SCHEMATHESIS_MAX_EXAMPLES)
    (RESULTS_DIRECTORY / "schemathesis.txt").write_text(completed.stdout, encoding="utf-8")

    assert completed.returncode == 0, completed.stdout[-3000:]
