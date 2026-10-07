import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from google.protobuf.descriptor_pool import DescriptorPool

from apigateway.config import GatewaySettings
from apigateway.config_files import GrpcServiceSource, RestServiceSource
from apigateway.grpc_tool_builder import GrpcToolBuilder
from apigateway.openapi_tool_builder import OpenApiToolBuilder
from apigateway.tool_definitions import ToolDefinition
from tests.fake_inventory import (
    SERVICE_NAME,
    FakeInventoryService,
    compile_inventory_descriptor_pool,
    start_fake_inventory_server,
)
from tests.snapshots import FIXTURES_DIRECTORY

ORDERS_BASE_URL = "http://orders.test"
ORDERS_SOURCE = RestServiceSource(
    kind="rest",
    name="orders",
    base_url=ORDERS_BASE_URL,
    openapi_url=f"{ORDERS_BASE_URL}/openapi.json",
)
ALL_ENABLED_OVERRIDES = {
    "orders_get_order": {"enabled": True, "description": "Look up one order."},
    "orders_list_orders": {"enabled": True},
    "orders_create_order": {"enabled": True},
    "orders_get_caller": {"enabled": True},
    "inventory_get_stock": {"enabled": True},
    "inventory_reserve_stock": {"enabled": True},
    "inventory_watch_stock": {"enabled": True},
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def orders_openapi_spec() -> dict[str, Any]:
    return json.loads((FIXTURES_DIRECTORY / "orders_openapi.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def inventory_descriptor_pool(tmp_path_factory: pytest.TempPathFactory) -> DescriptorPool:
    return compile_inventory_descriptor_pool(tmp_path_factory.mktemp("proto"))


@pytest.fixture
async def fake_inventory(
    inventory_descriptor_pool: DescriptorPool,
) -> AsyncIterator[tuple[FakeInventoryService, str]]:
    service = FakeInventoryService(inventory_descriptor_pool)
    server, target = await start_fake_inventory_server(service, inventory_descriptor_pool)
    yield service, target
    await server.stop(grace=None)


def build_inventory_tools(
    descriptor_pool: DescriptorPool, target: str = "inventory.test:50051"
) -> list[ToolDefinition]:
    source = GrpcServiceSource(kind="grpc", name="inventory", target=target)
    service = descriptor_pool.FindServiceByName(SERVICE_NAME)
    return GrpcToolBuilder(source, [service], descriptor_pool, max_schema_depth=6).build_tools()


def build_orders_tools(spec: dict[str, Any]) -> list[ToolDefinition]:
    return OpenApiToolBuilder(ORDERS_SOURCE, spec, max_schema_depth=6).build_tools()


def write_config_files(
    directory: Path,
    overrides: dict[str, Any],
    services: list[dict[str, Any]] | None = None,
) -> GatewaySettings:
    services_file = directory / "services.yaml"
    overrides_file = directory / "tool_overrides.yaml"
    default_services = [ORDERS_SOURCE.model_dump()]
    services_file.write_text(
        yaml.safe_dump({"services": services or default_services}), encoding="utf-8"
    )
    overrides_file.write_text(yaml.safe_dump({"tools": overrides}), encoding="utf-8")
    return GatewaySettings(
        services_file=services_file,
        overrides_file=overrides_file,
        retry_backoff_seconds=0,
    )
