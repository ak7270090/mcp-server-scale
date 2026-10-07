from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml

from apigateway.config_files import ServiceSource, load_services_file, load_tool_overrides
from apigateway.response_filters import ResponseFilter, project_fields
from apigateway.tool_definitions import ToolDefinition, to_snake_case
from apigateway.tool_registry import RegistryRefresher, ToolRegistry
from tests.conftest import build_orders_tools, write_config_files

pytestmark = pytest.mark.anyio

FILTER = ResponseFilter(
    {"email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "phone": r"\+\d[\d\s().-]{7,}\d"}
)


class FakeCrawler:
    def __init__(self, tools: list[ToolDefinition]) -> None:
        self.tools = tools
        self.is_failing = False

    async def discover(self, source: ServiceSource) -> list[ToolDefinition]:
        if self.is_failing:
            raise ConnectionError("backend down")
        return self.tools


async def build_registry(
    tmp_path: Path, spec: dict[str, Any], overrides: dict[str, Any]
) -> tuple[ToolRegistry, FakeCrawler]:
    crawler = FakeCrawler(build_orders_tools(spec))
    registry = ToolRegistry(write_config_files(tmp_path, overrides), crawler)
    await registry.refresh()
    return registry, crawler


async def test_discovered_tools_are_disabled_until_enabled(
    tmp_path: Path, orders_openapi_spec: dict[str, Any]
) -> None:
    registry, _ = await build_registry(
        tmp_path,
        orders_openapi_spec,
        {"orders_get_order": {"enabled": True, "description": "Reviewed text."}},
    )

    discovered = {tool["name"]: tool for tool in registry.describe_discovered_tools()}
    assert [tool.name for tool in registry.enabled_tools()] == ["orders_get_order"]
    assert registry.find_enabled_tool("orders_get_order").description == "Reviewed text."
    assert registry.find_enabled_tool("orders_cancel_order") is None
    assert len(discovered) == 5
    assert not discovered["orders_cancel_order"]["enabled"]


async def test_refresh_applies_edited_overrides(
    tmp_path: Path, orders_openapi_spec: dict[str, Any]
) -> None:
    registry, _ = await build_registry(tmp_path, orders_openapi_spec, {})
    assert registry.enabled_tools() == []

    (tmp_path / "tool_overrides.yaml").write_text(
        yaml.safe_dump({"tools": {"orders_cancel_order": {"enabled": True}}}), encoding="utf-8"
    )
    await registry.refresh()

    assert [tool.name for tool in registry.enabled_tools()] == ["orders_cancel_order"]


async def test_failed_discovery_keeps_known_tools(
    tmp_path: Path, orders_openapi_spec: dict[str, Any]
) -> None:
    registry, crawler = await build_registry(
        tmp_path, orders_openapi_spec, {"orders_get_order": {"enabled": True}}
    )
    crawler.is_failing = True

    await registry.refresh()

    assert registry.find_enabled_tool("orders_get_order") is not None


async def test_broken_overrides_file_keeps_previous_overrides(
    tmp_path: Path, orders_openapi_spec: dict[str, Any]
) -> None:
    registry, _ = await build_registry(
        tmp_path, orders_openapi_spec, {"orders_get_order": {"enabled": True}}
    )
    (tmp_path / "tool_overrides.yaml").write_text("tools: [not, a, mapping", encoding="utf-8")

    await registry.refresh()

    assert registry.find_enabled_tool("orders_get_order") is not None


async def test_refresher_refreshes_on_its_interval(
    tmp_path: Path, orders_openapi_spec: dict[str, Any]
) -> None:
    registry, _ = await build_registry(tmp_path, orders_openapi_spec, {})
    (tmp_path / "tool_overrides.yaml").write_text(
        yaml.safe_dump({"tools": {"orders_get_order": {"enabled": True}}}), encoding="utf-8"
    )

    with pytest.raises(TimeoutError), anyio.fail_after(0.3):
        await RegistryRefresher(registry, interval_seconds=0.05).run_forever()

    assert registry.find_enabled_tool("orders_get_order") is not None


def test_config_files_load(tmp_path: Path) -> None:
    settings = write_config_files(tmp_path, {"orders_get_order": {"enabled": True}})

    assert load_services_file(settings.services_file)[0].name == "orders"
    assert load_tool_overrides(settings.overrides_file)["orders_get_order"].enabled
    assert load_tool_overrides(tmp_path / "missing.yaml") == {}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("getOrder", "get_order"),
        ("GetStock", "get_stock"),
        ("delete-node", "delete_node"),
        ("listOrdersV2", "list_orders_v2"),
    ],
)
def test_operation_names_become_snake_case(name: str, expected: str) -> None:
    assert to_snake_case(name) == expected


def test_projection_keeps_requested_top_level_fields() -> None:
    assert project_fields({"id": 1, "email": "x", "total": 5}, ["id", "total"], False) == {
        "id": 1,
        "total": 5,
    }


def test_projection_applies_to_each_item_of_a_wrapped_list() -> None:
    wrapped = {"result": [{"id": 1, "status": "a", "x": 0}, {"id": 2, "status": "b"}]}

    assert project_fields(wrapped, ["id"], True) == {"result": [{"id": 1}, {"id": 2}]}
    assert project_fields({"result": {"id": 1, "x": 2}}, ["id"], True) == {"result": {"id": 1}}


def test_redaction_masks_pii_anywhere_in_the_result() -> None:
    result = {
        "id": 7,
        "customer_email": "ana@example.com",
        "notes": ["call +1 415 555 0100 after 5pm"],
        "created_at": "2026-10-08T10:00:00Z",
    }

    redacted = FILTER.apply(result, None, False)

    assert redacted == {
        "id": 7,
        "customer_email": "[REDACTED]",
        "notes": ["call [REDACTED] after 5pm"],
        "created_at": "2026-10-08T10:00:00Z",
    }
