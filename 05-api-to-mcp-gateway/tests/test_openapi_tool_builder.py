from typing import Any

import jsonschema
import pytest

from apigateway.config_files import RestServiceSource
from apigateway.openapi_tool_builder import OpenApiToolBuilder
from apigateway.tool_definitions import ArgumentLocation
from tests.conftest import build_orders_tools
from tests.snapshots import assert_matches_snapshot

SOURCE = RestServiceSource(
    kind="rest", name="shop", base_url="http://shop.test", openapi_url="http://shop.test/spec"
)
TRICKY_SPEC: dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/nodes/{node-id}": {
            "parameters": [{"$ref": "#/components/parameters/NodeId"}],
            "put": {
                "operationId": "updateNode",
                "parameters": [
                    {"name": "X-Request-Id", "in": "header", "schema": {"type": "string"}},
                    {"name": "session", "in": "cookie", "schema": {"type": "string"}},
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                    },
                },
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                        }
                    }
                },
            },
            "delete": {"operationId": "delete-node", "responses": {"204": {}}},
        },
        "/tags": {
            "post": {
                "operationId": "addTags",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    }
                },
            },
            "get": {"summary": "No operationId, so not a tool", "responses": {}},
        },
    },
    "components": {
        "parameters": {
            "NodeId": {"name": "node-id", "in": "path", "schema": {"type": "string"}},
        },
        "schemas": {
            "Node": {
                "type": "object",
                "required": ["label"],
                "properties": {
                    "label": {"type": "string"},
                    "node-id": {"type": "string"},
                    "child": {"$ref": "#/components/schemas/Node"},
                },
            }
        },
    },
}


def build_tricky_tools() -> dict[str, Any]:
    tools = OpenApiToolBuilder(SOURCE, TRICKY_SPEC, max_schema_depth=2).build_tools()
    return {tool.name: tool for tool in tools}


def test_orders_tools_match_snapshot(orders_openapi_spec: dict[str, Any]) -> None:
    assert_matches_snapshot(build_orders_tools(orders_openapi_spec), "expected_orders_tools.json")


def test_generated_schemas_are_valid_json_schema(orders_openapi_spec: dict[str, Any]) -> None:
    for tool in build_orders_tools(orders_openapi_spec):
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        if tool.output_schema is not None:
            jsonschema.Draft202012Validator.check_schema(tool.output_schema)


def test_operations_without_operation_id_are_skipped() -> None:
    assert set(build_tricky_tools()) == {"shop_update_node", "shop_delete_node", "shop_add_tags"}


def test_parameters_and_body_fields_get_their_locations() -> None:
    bindings = build_tricky_tools()["shop_update_node"].route.argument_bindings

    assert bindings["node-id"].location == ArgumentLocation.PATH
    assert bindings["X-Request-Id"].location == ArgumentLocation.HEADER
    assert bindings["label"].location == ArgumentLocation.BODY_FIELD
    assert "session" not in bindings


def test_body_field_clashing_with_a_parameter_is_prefixed() -> None:
    tool = build_tricky_tools()["shop_update_node"]

    assert tool.route.argument_bindings["body_node-id"].wire_name == "node-id"
    assert set(tool.input_schema["required"]) == {"node-id", "label"}


def test_recursive_reference_stops_at_depth_limit() -> None:
    child = build_tricky_tools()["shop_update_node"].output_schema["properties"]["child"]

    assert child["properties"]["child"]["description"].startswith("Nested schema truncated")


def test_array_body_and_array_result_are_wrapped() -> None:
    tool = build_tricky_tools()["shop_add_tags"]

    assert tool.route.argument_bindings["body"].location == ArgumentLocation.WHOLE_BODY
    assert tool.route.is_result_wrapped
    assert tool.output_schema["properties"]["result"]["type"] == "array"


def test_operation_without_json_result_has_no_output_schema() -> None:
    tool = build_tricky_tools()["shop_delete_node"]

    assert tool.output_schema is None
    assert tool.is_destructive
    assert "fields" not in tool.input_schema["properties"]


def test_external_references_are_rejected() -> None:
    builder = OpenApiToolBuilder(SOURCE, TRICKY_SPEC, max_schema_depth=2)

    with pytest.raises(ValueError, match="only local references"):
        builder.resolve_schema({"$ref": "https://example.com/schema.json"})
