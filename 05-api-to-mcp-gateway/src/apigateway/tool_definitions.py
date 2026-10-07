"""What the control plane produces and the data plane consumes: tools and their routes."""

import functools
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import jsonschema
from google.protobuf.descriptor import Descriptor
from google.protobuf.descriptor_pool import DescriptorPool
from mcp import types

from apigateway.constants import FIELDS_ARGUMENT, TOOL_NAME_SEPARATOR, WRAPPED_RESULT_KEY

FIELDS_ARGUMENT_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Optional. Return only these top-level fields of the result.",
}


class ArgumentLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    BODY_FIELD = "body_field"
    WHOLE_BODY = "whole_body"


@dataclass(frozen=True)
class ArgumentBinding:
    location: ArgumentLocation
    wire_name: str


@dataclass(frozen=True)
class RestRoute:
    base_url: str
    method: str
    path_template: str
    argument_bindings: dict[str, ArgumentBinding]
    is_result_wrapped: bool


@dataclass(frozen=True)
class GrpcRoute:
    target: str
    service_full_name: str
    method_name: str
    input_descriptor: Descriptor
    output_descriptor: Descriptor
    is_server_streaming: bool
    descriptor_pool: DescriptorPool = field(repr=False, compare=False)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    service_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    is_read_only: bool
    is_destructive: bool
    route: RestRoute | GrpcRoute

    @property
    def is_result_wrapped(self) -> bool:
        return isinstance(self.route, RestRoute) and self.route.is_result_wrapped

    @functools.cached_property
    def input_validator(self) -> jsonschema.protocols.Validator:
        """Compiled once per tool; ``jsonschema.validate()`` re-checks the schema on every call."""
        validator_class = jsonschema.validators.validator_for(self.input_schema)
        return validator_class(self.input_schema)

    def to_mcp_tool(self) -> types.Tool:
        return types.Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
            outputSchema=self.output_schema,
            annotations=types.ToolAnnotations(
                readOnlyHint=self.is_read_only,
                destructiveHint=self.is_destructive,
                openWorldHint=True,
            ),
        )


def to_snake_case(name: str) -> str:
    """``getOrder`` / ``GetOrder`` / ``get-order`` → ``get_order``."""
    with_separators = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-zA-Z0-9]+", "_", with_separators).strip("_").lower()


def build_tool_name(service_name: str, operation_name: str) -> str:
    return f"{service_name}{TOOL_NAME_SEPARATOR}{to_snake_case(operation_name)}"


def strip_required(schema: Any) -> Any:
    """Output schemas without ``required``, so a projected result (``fields``) still validates."""
    if isinstance(schema, dict):
        return {key: strip_required(value) for key, value in schema.items() if key != "required"}
    if isinstance(schema, list):
        return [strip_required(item) for item in schema]
    return schema


def build_output_schema(result_schema: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """MCP structured output must be an object: non-object results are wrapped in ``result``.

    Returns the output schema and whether results are wrapped.
    """
    if result_schema is None:
        return None, False
    if result_schema.get("type") == "object":
        return strip_required(result_schema), False
    wrapped_schema = {
        "type": "object",
        "properties": {WRAPPED_RESULT_KEY: strip_required(result_schema)},
    }
    return wrapped_schema, True


def add_fields_argument(input_schema: dict[str, Any]) -> dict[str, Any]:
    properties = {**input_schema.get("properties", {}), FIELDS_ARGUMENT: FIELDS_ARGUMENT_SCHEMA}
    return {**input_schema, "properties": properties}
