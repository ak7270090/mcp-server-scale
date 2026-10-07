"""In-process inventory gRPC server built from the real .proto, with reflection and recording."""

import subprocess
import sys
from collections.abc import AsyncIterator
from importlib import resources
from pathlib import Path
from typing import Any

import grpc
from google.protobuf import descriptor_pb2, message_factory
from google.protobuf.descriptor_pool import DescriptorPool
from grpc_reflection.v1alpha import reflection

PROTO_DIRECTORY = Path(__file__).resolve().parents[1] / "backends" / "inventory_grpc" / "proto"
PROTO_FILE = "inventory/v1/inventory.proto"
SERVICE_NAME = "inventory.v1.InventoryService"
MISSING_SKU = "SKU-404"
FLAKY_SKU = "SKU-FLAKY"
LARGE_STOCK = 12345678901
WATCH_UPDATE_COUNT = 3


def compile_inventory_descriptor_pool(output_directory: Path) -> DescriptorPool:
    """Compile the backend's proto (with imports) and load it into a fresh descriptor pool."""
    descriptor_set_path = output_directory / "inventory.desc"
    well_known_protos = resources.files("grpc_tools") / "_proto"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{PROTO_DIRECTORY}",
            f"-I{well_known_protos}",
            "--include_imports",
            f"--descriptor_set_out={descriptor_set_path}",
            PROTO_FILE,
        ],
        check=True,
    )
    descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(descriptor_set_path.read_bytes())
    descriptor_pool = DescriptorPool()
    for file_descriptor in descriptor_set.file:
        descriptor_pool.AddSerializedFile(file_descriptor.SerializeToString())
    return descriptor_pool


class FakeInventoryService:
    """Records requests and metadata; ``SKU-404`` is NOT_FOUND, ``SKU-FLAKY`` fails first."""

    def __init__(self, descriptor_pool: DescriptorPool, flaky_failure_count: int = 2) -> None:
        self._message_classes = {
            name: message_factory.GetMessageClass(
                descriptor_pool.FindMessageTypeByName(f"inventory.v1.{name}")
            )
            for name in (
                "GetStockRequest",
                "StockLevel",
                "ReserveStockRequest",
                "Reservation",
                "WatchStockRequest",
            )
        }
        self._remaining_flaky_failures = flaky_failure_count
        self.received_requests: list[tuple[str, Any]] = []
        self.received_metadata: list[dict[str, str]] = []

    def build_handler(self) -> grpc.GenericRpcHandler:
        classes = self._message_classes
        return grpc.method_handlers_generic_handler(
            SERVICE_NAME,
            {
                "GetStock": grpc.unary_unary_rpc_method_handler(
                    self.get_stock,
                    request_deserializer=classes["GetStockRequest"].FromString,
                    response_serializer=classes["StockLevel"].SerializeToString,
                ),
                "ReserveStock": grpc.unary_unary_rpc_method_handler(
                    self.reserve_stock,
                    request_deserializer=classes["ReserveStockRequest"].FromString,
                    response_serializer=classes["Reservation"].SerializeToString,
                ),
                "WatchStock": grpc.unary_stream_rpc_method_handler(
                    self.watch_stock,
                    request_deserializer=classes["WatchStockRequest"].FromString,
                    response_serializer=classes["StockLevel"].SerializeToString,
                ),
            },
        )

    def _record(self, method_name: str, request: Any, context: grpc.aio.ServicerContext) -> None:
        self.received_requests.append((method_name, request))
        self.received_metadata.append(dict(context.invocation_metadata()))

    def _build_stock_level(self, sku: str) -> Any:
        stock_level = self._message_classes["StockLevel"](sku=sku, available=LARGE_STOCK, status=1)
        stock_level.warehouse.code = "AMS1"
        stock_level.warehouse.city = "Amsterdam"
        stock_level.updated_at.FromSeconds(1_700_000_000)
        return stock_level

    async def get_stock(self, request: Any, context: grpc.aio.ServicerContext) -> Any:
        self._record("GetStock", request, context)
        if request.sku == MISSING_SKU:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"unknown sku {request.sku!r}")
        if request.sku == FLAKY_SKU and self._remaining_flaky_failures > 0:
            self._remaining_flaky_failures -= 1
            await context.abort(grpc.StatusCode.UNAVAILABLE, "warming up")
        return self._build_stock_level(request.sku)

    async def reserve_stock(self, request: Any, context: grpc.aio.ServicerContext) -> Any:
        self._record("ReserveStock", request, context)
        return self._message_classes["Reservation"](
            reservation_id="r-1", sku=request.sku, quantity=request.quantity, remaining=7
        )

    async def watch_stock(
        self, request: Any, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[Any]:
        self._record("WatchStock", request, context)
        for _ in range(WATCH_UPDATE_COUNT):
            yield self._build_stock_level(request.sku)


async def start_fake_inventory_server(
    service: FakeInventoryService, descriptor_pool: DescriptorPool
) -> tuple[grpc.aio.Server, str]:
    server = grpc.aio.server()
    server.add_generic_rpc_handlers((service.build_handler(),))
    reflection.enable_server_reflection(
        (SERVICE_NAME, reflection.SERVICE_NAME), server, pool=descriptor_pool
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    return server, f"localhost:{port}"
