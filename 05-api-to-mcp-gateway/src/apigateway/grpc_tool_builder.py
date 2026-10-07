"""gRPC method → MCP tool definition, with JSON Schemas from the proto3 JSON mapping."""

from typing import Any

import grpc
from google.protobuf.descriptor import Descriptor, FieldDescriptor, ServiceDescriptor
from google.protobuf.descriptor_pool import DescriptorPool
from grpc_reflection.v1alpha.proto_reflection_descriptor_database import (
    ProtoReflectionDescriptorDatabase,
)

from apigateway.config_files import GrpcServiceSource
from apigateway.constants import INT64_PATTERN, REFLECTION_SERVICE_PREFIX
from apigateway.tool_definitions import (
    GrpcRoute,
    ToolDefinition,
    add_fields_argument,
    build_output_schema,
    build_tool_name,
)

INTEGER_SCHEMA = {"type": "integer"}
INT64_SCHEMA = {"type": ["integer", "string"], "pattern": INT64_PATTERN}
SCALAR_SCHEMAS = {
    FieldDescriptor.TYPE_DOUBLE: {"type": "number"},
    FieldDescriptor.TYPE_FLOAT: {"type": "number"},
    FieldDescriptor.TYPE_INT32: INTEGER_SCHEMA,
    FieldDescriptor.TYPE_SINT32: INTEGER_SCHEMA,
    FieldDescriptor.TYPE_SFIXED32: INTEGER_SCHEMA,
    FieldDescriptor.TYPE_UINT32: INTEGER_SCHEMA,
    FieldDescriptor.TYPE_FIXED32: INTEGER_SCHEMA,
    FieldDescriptor.TYPE_INT64: INT64_SCHEMA,
    FieldDescriptor.TYPE_SINT64: INT64_SCHEMA,
    FieldDescriptor.TYPE_SFIXED64: INT64_SCHEMA,
    FieldDescriptor.TYPE_UINT64: INT64_SCHEMA,
    FieldDescriptor.TYPE_FIXED64: INT64_SCHEMA,
    FieldDescriptor.TYPE_BOOL: {"type": "boolean"},
    FieldDescriptor.TYPE_STRING: {"type": "string"},
    FieldDescriptor.TYPE_BYTES: {"type": "string", "contentEncoding": "base64"},
}
WELL_KNOWN_TYPE_SCHEMAS = {
    "google.protobuf.Timestamp": {"type": "string", "format": "date-time"},
    "google.protobuf.Duration": {"type": "string", "pattern": r"^-?\d+(\.\d+)?s$"},
    "google.protobuf.Struct": {"type": "object"},
    "google.protobuf.Value": {},
    "google.protobuf.ListValue": {"type": "array"},
    "google.protobuf.Empty": {"type": "object"},
    "google.protobuf.StringValue": {"type": "string"},
    "google.protobuf.BoolValue": {"type": "boolean"},
    "google.protobuf.Int32Value": INTEGER_SCHEMA,
    "google.protobuf.Int64Value": INT64_SCHEMA,
    "google.protobuf.DoubleValue": {"type": "number"},
}
STREAMING_DESCRIPTION_SUFFIX = (
    " Streams updates: each update is reported as progress; the last one is the result."
)


class ProtoSchemaBuilder:
    def __init__(self, max_depth: int) -> None:
        self._max_depth = max_depth

    def message_schema(self, descriptor: Descriptor, depth: int = 0) -> dict[str, Any]:
        if descriptor.full_name in WELL_KNOWN_TYPE_SCHEMAS:
            return dict(WELL_KNOWN_TYPE_SCHEMAS[descriptor.full_name])
        if depth > self._max_depth:
            return {"type": "object"}
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                field.json_name: self._field_schema(field, depth) for field in descriptor.fields
            },
            "additionalProperties": False,
        }
        oneof_constraints = [
            self._at_most_one_of([field.json_name for field in oneof.fields])
            for oneof in descriptor.oneofs
            if not oneof.name.startswith("_")
        ]
        if oneof_constraints:
            schema["allOf"] = oneof_constraints
        return schema

    def _field_schema(self, field: FieldDescriptor, depth: int) -> dict[str, Any]:
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            value_field = field.message_type.fields_by_name["value"]
            return {
                "type": "object",
                "additionalProperties": self._value_schema(value_field, depth),
            }
        value_schema = self._value_schema(field, depth)
        if field.is_repeated:
            return {"type": "array", "items": value_schema}
        return value_schema

    def _value_schema(self, field: FieldDescriptor, depth: int) -> dict[str, Any]:
        if field.type == FieldDescriptor.TYPE_ENUM:
            return {"type": "string", "enum": [value.name for value in field.enum_type.values]}
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            return self.message_schema(field.message_type, depth + 1)
        return dict(SCALAR_SCHEMAS[field.type])

    @staticmethod
    def _at_most_one_of(field_names: list[str]) -> dict[str, Any]:
        """A proto oneof: exactly one of the fields, or none of them."""
        choices: list[dict[str, Any]] = [{"required": [name]} for name in field_names]
        return {"oneOf": [*choices, {"not": {"anyOf": choices}}]}


class GrpcToolBuilder:
    def __init__(
        self,
        source: GrpcServiceSource,
        services: list[ServiceDescriptor],
        descriptor_pool: DescriptorPool,
        max_schema_depth: int,
    ) -> None:
        self._source = source
        self._services = services
        self._descriptor_pool = descriptor_pool
        self._schema_builder = ProtoSchemaBuilder(max_schema_depth)

    def build_tools(self) -> list[ToolDefinition]:
        return [
            self._build_tool(service, method)
            for service in self._services
            for method in service.methods
            if not method.client_streaming
        ]

    def _build_tool(self, service: ServiceDescriptor, method: Any) -> ToolDefinition:
        output_schema, _ = build_output_schema(
            self._schema_builder.message_schema(method.output_type)
        )
        description = f"{service.full_name}.{method.name}."
        if method.server_streaming:
            description += STREAMING_DESCRIPTION_SUFFIX
        return ToolDefinition(
            name=build_tool_name(self._source.name, method.name),
            service_name=self._source.name,
            description=description,
            input_schema=add_fields_argument(
                self._schema_builder.message_schema(method.input_type)
            ),
            output_schema=output_schema,
            is_read_only=method.name.startswith(tuple(self._source.read_only_method_prefixes)),
            is_destructive=False,
            route=GrpcRoute(
                target=self._source.target,
                service_full_name=service.full_name,
                method_name=method.name,
                input_descriptor=method.input_type,
                output_descriptor=method.output_type,
                is_server_streaming=method.server_streaming,
                descriptor_pool=self._descriptor_pool,
            ),
        )


def load_service_descriptors(
    target: str, timeout_seconds: float
) -> tuple[list[ServiceDescriptor], DescriptorPool]:
    """Blocking: read every service (except reflection itself) through server reflection."""
    channel = grpc.insecure_channel(target)
    try:
        grpc.channel_ready_future(channel).result(timeout=timeout_seconds)
        descriptor_database = ProtoReflectionDescriptorDatabase(channel)
        descriptor_pool = DescriptorPool(descriptor_database)
        services = [
            descriptor_pool.FindServiceByName(service_name)
            for service_name in descriptor_database.get_services()
            if not service_name.startswith(REFLECTION_SERVICE_PREFIX)
        ]
    finally:
        channel.close()
    return services, descriptor_pool
