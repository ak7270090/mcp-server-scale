"""MCP arguments → HTTP request; HTTP response → JSON result."""

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from apigateway.error_mapping import BackendCallError, map_http_failure, map_transport_failure
from apigateway.tool_definitions import ArgumentLocation, RestRoute


@dataclass
class HttpRequestParts:
    path: str
    query_parameters: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any = None


def build_http_request_parts(route: RestRoute, arguments: dict[str, Any]) -> HttpRequestParts:
    """Place each argument where the OpenAPI operation expects it."""
    parts = HttpRequestParts(path=route.path_template)
    body_fields: dict[str, Any] = {}
    for argument_name, binding in route.argument_bindings.items():
        if argument_name not in arguments:
            continue
        value = arguments[argument_name]
        if binding.location == ArgumentLocation.PATH:
            parts.path = parts.path.replace(f"{{{binding.wire_name}}}", quote(str(value), safe=""))
        elif binding.location == ArgumentLocation.QUERY:
            parts.query_parameters[binding.wire_name] = value
        elif binding.location == ArgumentLocation.HEADER:
            parts.headers[binding.wire_name] = str(value)
        elif binding.location == ArgumentLocation.BODY_FIELD:
            body_fields[binding.wire_name] = value
        else:
            parts.json_body = value
    if body_fields:
        parts.json_body = body_fields
    return parts


class RestInvoker:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def invoke(
        self, route: RestRoute, arguments: dict[str, Any], passthrough_headers: dict[str, str]
    ) -> Any:
        parts = build_http_request_parts(route, arguments)
        request = self._http_client.build_request(
            route.method,
            f"{route.base_url.rstrip('/')}{parts.path}",
            params=parts.query_parameters,
            headers={**passthrough_headers, **parts.headers},
            json=parts.json_body,
        )
        try:
            response = await self._http_client.send(request)
        except httpx.TransportError as error:
            raise BackendCallError(map_transport_failure(error)) from error
        if response.status_code >= 400:
            raise BackendCallError(map_http_failure(response.status_code, response.text))
        return response.json() if response.content else None
