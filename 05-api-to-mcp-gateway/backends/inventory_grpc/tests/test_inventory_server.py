from collections.abc import AsyncIterator

import grpc
import pytest

from inventory.v1 import inventory_pb2, inventory_pb2_grpc
from inventoryservice.server import create_inventory_server


@pytest.fixture
async def inventory_stub() -> AsyncIterator[inventory_pb2_grpc.InventoryServiceStub]:
    server, port = create_inventory_server("localhost:0")
    await server.start()
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        yield inventory_pb2_grpc.InventoryServiceStub(channel)
    await server.stop(grace=None)


async def read_stock(stub: inventory_pb2_grpc.InventoryServiceStub, sku: str):
    return await stub.GetStock(inventory_pb2.GetStockRequest(sku=sku))


@pytest.mark.anyio
async def test_get_stock_reports_status_and_warehouse(inventory_stub) -> None:
    stock = await read_stock(inventory_stub, "SKU-002")

    assert stock.available == 3
    assert stock.status == inventory_pb2.LOW_STOCK
    assert stock.warehouse.city == "Bengaluru"


@pytest.mark.anyio
async def test_unknown_sku_is_not_found(inventory_stub) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await read_stock(inventory_stub, "SKU-999")

    assert error.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.anyio
async def test_reserve_reduces_stock_and_rejects_too_many(inventory_stub) -> None:
    reservation = await inventory_stub.ReserveStock(
        inventory_pb2.ReserveStockRequest(sku="SKU-001", quantity=5, hold_minutes=30)
    )
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await inventory_stub.ReserveStock(
            inventory_pb2.ReserveStockRequest(sku="SKU-001", quantity=500)
        )

    assert reservation.remaining == 20
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.anyio
async def test_watch_streams_the_requested_number_of_updates(inventory_stub) -> None:
    updates = [
        update
        async for update in inventory_stub.WatchStock(
            inventory_pb2.WatchStockRequest(sku="SKU-001", updates=3, interval_ms=1)
        )
    ]

    assert len(updates) == 3
