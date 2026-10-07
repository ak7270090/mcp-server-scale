"""OpenAPI operation → MCP tool definition (one tool per ``operationId``)."""

import re
from typing import Any

from apigateway.config_files import RestServiceSource
from apigateway.constants import (
    BODY_ARGUMENT,
    BODY_ARGUMENT_PREFIX,
    COMPONENT_REFERENCE_PREFIX,
    HTTP_METHODS,
    JSON_MEDIA_TYPE,
    SUCCESS_STATUS_PATTERN,
)
from apigateway.tool_definitions import (
    ArgumentBinding,
    ArgumentLocation,
    RestRoute,
    ToolDefinition,
    add_fields_argument,
    build_output_schema,
    build_tool_name,
)

PARAMETER_LOCATIONS = {
    "path": ArgumentLocation.PATH,
    "query": ArgumentLocation.QUERY,
    "header": ArgumentLocation.HEADER,
}
TRUNCATED_SCHEMA = {"type": "object", "description": "Nested schema truncated (depth limit)."}


class OpenApiToolBuilder:
    def __init__(self, source: RestServiceSource, spec: dict[str, Any], max_schema_depth: int):
        self._source = source
        self._spec = spec
        self._max_schema_depth = max_schema_depth

    def build_tools(self) -> list[ToolDefinition]:
        tools = []
        for path, path_item in self._spec.get("paths", {}).items():
            shared_parameters = path_item.get("parameters", [])
            for method in HTTP_METHODS:
                operation = path_item.get(method)
                if operation and operation.get("operationId"):
                    tools.append(self._build_tool(path, method, operation, shared_parameters))
        return tools

    def resolve_schema(self, schema: Any, depth: int = 0) -> Any:
        """Inline every ``$ref``; references nested deeper than the limit become a plain object."""
        if isinstance(schema, list):
            return [self.resolve_schema(item, depth) for item in schema]
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema:
            if depth >= self._max_schema_depth:
                return dict(TRUNCATED_SCHEMA)
            siblings = {key: value for key, value in schema.items() if key != "$ref"}
            return self.resolve_schema(
                {**self._find_reference(schema["$ref"]), **siblings}, depth + 1
            )
        return {key: self.resolve_schema(value, depth) for key, value in schema.items()}

    def _find_reference(self, reference: str) -> dict[str, Any]:
        if not reference.startswith(COMPONENT_REFERENCE_PREFIX):
            raise ValueError(f"only local references are supported, got {reference!r}")
        target: Any = self._spec
        for part in reference.removeprefix(COMPONENT_REFERENCE_PREFIX).split("/"):
            target = target[part]
        return target

    def _build_tool(
        self,
        path: str,
        method: str,
        operation: dict[str, Any],
        shared_parameters: list[dict[str, Any]],
    ) -> ToolDefinition:
        properties: dict[str, Any] = {}
        required: list[str] = []
        bindings: dict[str, ArgumentBinding] = {}
        for parameter in [*shared_parameters, *operation.get("parameters", [])]:
            self._add_parameter(self.resolve_schema(parameter), properties, required, bindings)
        self._add_request_body(operation.get("requestBody"), properties, required, bindings)
        output_schema, is_result_wrapped = build_output_schema(self._find_result_schema(operation))
        input_schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        if output_schema is not None:
            input_schema = add_fields_argument(input_schema)
        return ToolDefinition(
            name=build_tool_name(self._source.name, operation["operationId"]),
            service_name=self._source.name,
            description=operation.get("summary")
            or operation.get("description")
            or f"{method.upper()} {path}",
            input_schema=input_schema,
            output_schema=output_schema,
            is_read_only=method == "get",
            is_destructive=method == "delete",
            route=RestRoute(
                base_url=self._source.base_url,
                method=method.upper(),
                path_template=path,
                argument_bindings=bindings,
                is_result_wrapped=is_result_wrapped,
            ),
        )

    @staticmethod
    def _add_parameter(
        parameter: dict[str, Any],
        properties: dict[str, Any],
        required: list[str],
        bindings: dict[str, ArgumentBinding],
    ) -> None:
        location = PARAMETER_LOCATIONS.get(parameter.get("in"))
        if location is None:
            return
        name = parameter["name"]
        schema = dict(parameter.get("schema", {}))
        if parameter.get("description"):
            schema["description"] = parameter["description"]
        properties[name] = schema
        bindings[name] = ArgumentBinding(location, name)
        if parameter.get("required") or location == ArgumentLocation.PATH:
            required.append(name)

    def _add_request_body(
        self,
        request_body: dict[str, Any] | None,
        properties: dict[str, Any],
        required: list[str],
        bindings: dict[str, ArgumentBinding],
    ) -> None:
        if not request_body:
            return
        request_body = self.resolve_schema(request_body)
        body_schema = request_body.get("content", {}).get(JSON_MEDIA_TYPE, {}).get("schema")
        if body_schema is None:
            return
        is_body_required = bool(request_body.get("required"))
        if body_schema.get("type") != "object" or "properties" not in body_schema:
            properties[BODY_ARGUMENT] = body_schema
            bindings[BODY_ARGUMENT] = ArgumentBinding(ArgumentLocation.WHOLE_BODY, BODY_ARGUMENT)
            if is_body_required:
                required.append(BODY_ARGUMENT)
            return
        required_body_fields = set(body_schema.get("required", []))
        for field_name, field_schema in body_schema["properties"].items():
            argument_name = field_name
            if argument_name in properties:
                argument_name = f"{BODY_ARGUMENT_PREFIX}{field_name}"
            properties[argument_name] = field_schema
            bindings[argument_name] = ArgumentBinding(ArgumentLocation.BODY_FIELD, field_name)
            if is_body_required and field_name in required_body_fields:
                required.append(argument_name)

    def _find_result_schema(self, operation: dict[str, Any]) -> dict[str, Any] | None:
        for status_code, response in sorted(operation.get("responses", {}).items()):
            if not re.fullmatch(SUCCESS_STATUS_PATTERN, str(status_code)):
                continue
            response = self.resolve_schema(response)
            schema = response.get("content", {}).get(JSON_MEDIA_TYPE, {}).get("schema")
            if schema is not None:
                return schema
        return None
