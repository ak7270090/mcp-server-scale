"""gRPC servicer and server (``inventory.v1`` code is generated from proto/ at build time)."""

import asyncio
from collections.abc import AsyncIterator

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_reflection.v1alpha import reflection

from inventory.v1 import inventory_pb2, inventory_pb2_grpc
from inventoryservice.stock_store import (
    InsufficientStockError,
    StockSnapshot,
    StockStore,
    UnknownSkuError,
)

DEFAULT_PORT = 50051
MAX_WATCH_UPDATES = 20
DEFAULT_WATCH_INTERVAL_MS = 500


def build_stock_level(snapshot: StockSnapshot) -> inventory_pb2.StockLevel:
    updated_at = Timestamp()
    updated_at.GetCurrentTime()
    return inventory_pb2.StockLevel(
        sku=snapshot.sku,
        available=snapshot.available,
        status=inventory_pb2.StockStatus.Value(snapshot.status_name),
        warehouse=inventory_pb2.Warehouse(
            code=snapshot.warehouse_code, city=snapshot.warehouse_city
        ),
        updated_at=updated_at,
    )


class InventoryServicer(inventory_pb2_grpc.InventoryServiceServicer):
    def __init__(self, stock_store: StockStore) -> None:
        self._stock_store = stock_store

    async def GetStock(  # noqa: N802 - name fixed by the generated base class
        self, request: inventory_pb2.GetStockRequest, context: grpc.aio.ServicerContext
    ) -> inventory_pb2.StockLevel:
        return build_stock_level(await self._read_or_abort(request.sku, context))

    async def ReserveStock(  # noqa: N802
        self, request: inventory_pb2.ReserveStockRequest, context: grpc.aio.ServicerContext
    ) -> inventory_pb2.Reservation:
        if request.quantity <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be positive")
        try:
            reservation_id, remaining = self._stock_store.reserve(request.sku, request.quantity)
        except UnknownSkuError as error:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(error))
        except InsufficientStockError as error:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))
        return inventory_pb2.Reservation(
            reservation_id=reservation_id,
            sku=request.sku,
            quantity=request.quantity,
            remaining=remaining,
        )

    async def WatchStock(  # noqa: N802
        self, request: inventory_pb2.WatchStockRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[inventory_pb2.StockLevel]:
        await self._read_or_abort(request.sku, context)
        update_count = min(max(request.updates, 1), MAX_WATCH_UPDATES)
        interval_seconds = (request.interval_ms or DEFAULT_WATCH_INTERVAL_MS) / 1000
        for _ in range(update_count):
            yield build_stock_level(self._stock_store.read(request.sku))
            await asyncio.sleep(interval_seconds)

    async def _read_or_abort(self, sku: str, context: grpc.aio.ServicerContext) -> StockSnapshot:
        try:
            return self._stock_store.read(sku)
        except UnknownSkuError as error:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(error))


def create_inventory_server(listen_address: str) -> tuple[grpc.aio.Server, int]:
    """Server with reflection, bound to ``listen_address`` (port 0 picks a free port)."""
    server = grpc.aio.server()
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(
        InventoryServicer(StockStore()), server
    )
    service_names = (
        inventory_pb2.DESCRIPTOR.services_by_name["InventoryService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)
    bound_port = server.add_insecure_port(listen_address)
    return server, bound_port


async def serve(port: int = DEFAULT_PORT) -> None:
    server, _ = create_inventory_server(f"[::]:{port}")
    await server.start()
    await server.wait_for_termination()
