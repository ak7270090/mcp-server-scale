import jsonschema
import pytest
from google.protobuf.descriptor_pool import DescriptorPool

from apigateway.tool_definitions import ToolDefinition
from tests.conftest import build_inventory_tools
from tests.snapshots import assert_matches_snapshot


@pytest.fixture(scope="module")
def inventory_tools(inventory_descriptor_pool: DescriptorPool) -> dict[str, ToolDefinition]:
    return {tool.name: tool for tool in build_inventory_tools(inventory_descriptor_pool)}


def test_inventory_tools_match_snapshot(inventory_tools: dict[str, ToolDefinition]) -> None:
    assert_matches_snapshot(list(inventory_tools.values()), "expected_inventory_tools.json")


def test_schemas_are_valid_json_schema(inventory_tools: dict[str, ToolDefinition]) -> None:
    for tool in inventory_tools.values():
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        jsonschema.Draft202012Validator.check_schema(tool.output_schema)


def test_proto3_json_mapping_of_field_types(inventory_tools: dict[str, ToolDefinition]) -> None:
    stock_level = inventory_tools["inventory_get_stock"].output_schema["properties"]
    reserve_input = inventory_tools["inventory_reserve_stock"].input_schema["properties"]

    assert stock_level["available"]["type"] == ["integer", "string"]
    assert stock_level["status"]["enum"] == [
        "STOCK_STATUS_UNSPECIFIED",
        "IN_STOCK",
        "LOW_STOCK",
        "OUT_OF_STOCK",
    ]
    assert stock_level["updatedAt"] == {"type": "string", "format": "date-time"}
    assert stock_level["warehouse"]["properties"]["city"] == {"type": "string"}
    assert reserve_input["notes"] == {"type": "array", "items": {"type": "string"}}
    assert reserve_input["labels"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }


@pytest.mark.parametrize(
    ("arguments", "is_valid"),
    [
        ({"sku": "A", "quantity": 1}, True),
        ({"sku": "A", "quantity": 1, "holdMinutes": 5}, True),
        ({"sku": "A", "quantity": 1, "untilShipped": True}, True),
        ({"sku": "A", "quantity": 1, "holdMinutes": 5, "untilShipped": True}, False),
    ],
)
def test_oneof_allows_at_most_one_member(
    inventory_tools: dict[str, ToolDefinition], arguments: dict, is_valid: bool
) -> None:
    validator = jsonschema.Draft202012Validator(
        inventory_tools["inventory_reserve_stock"].input_schema
    )

    assert validator.is_valid(arguments) is is_valid


def test_streaming_and_read_only_are_detected(inventory_tools: dict[str, ToolDefinition]) -> None:
    watch = inventory_tools["inventory_watch_stock"]
    reserve = inventory_tools["inventory_reserve_stock"]

    assert watch.route.is_server_streaming
    assert "Streams updates" in watch.description
    assert watch.is_read_only
    assert not reserve.is_read_only
