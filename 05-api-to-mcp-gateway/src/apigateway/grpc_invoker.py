"""MCP arguments → protobuf request over a dynamic gRPC call; protobuf replies → JSON."""

import json
from typing import Any, Protocol

import grpc
from google.protobuf import json_format, message_factory
from google.protobuf.message import Message

from apigateway.config import GatewaySettings
from apigateway.error_mapping import BackendCallError, BackendFailure, map_grpc_failure
from apigateway.tool_definitions import GrpcRoute


class ProgressReporter(Protocol):
    async def report(self, progress: float, total: float | None, message: str | None) -> None: ...


def message_to_json(message: Message) -> dict[str, Any]:
    """Proto3 JSON mapping: camelCase names, int64 as strings, enum names, defaults included."""
    return json_format.MessageToDict(message, always_print_fields_with_no_presence=True)


class GrpcInvoker:
    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._channels: dict[str, grpc.aio.Channel] = {}

    async def close(self) -> None:
        for channel in self._channels.values():
            await channel.close()
        self._channels.clear()

    async def invoke(
        self,
        route: GrpcRoute,
        arguments: dict[str, Any],
        passthrough_headers: dict[str, str],
        progress_reporter: ProgressReporter,
    ) -> dict[str, Any]:
        request_class = message_factory.GetMessageClass(route.input_descriptor)
        response_class = message_factory.GetMessageClass(route.output_descriptor)
        request = request_class()
        try:
            json_format.ParseDict(arguments, request)
        except json_format.ParseError as error:
            failure = BackendFailure(
                f"arguments do not match {route.input_descriptor.full_name}: {error}",
                is_retryable=False,
            )
            raise BackendCallError(failure) from error
        method_path = f"/{route.service_full_name}/{route.method_name}"
        metadata = tuple(passthrough_headers.items())
        channel = self._get_channel(route.target)
        try:
            if route.is_server_streaming:
                stream = channel.unary_stream(
                    method_path,
                    request_serializer=request_class.SerializeToString,
                    response_deserializer=response_class.FromString,
                )(request, metadata=metadata, timeout=self._settings.grpc_stream_timeout_seconds)
                return await self._collect_stream(stream, progress_reporter)
            call = channel.unary_unary(
                method_path,
                request_serializer=request_class.SerializeToString,
                response_deserializer=response_class.FromString,
            )
            response = await call(
                request, metadata=metadata, timeout=self._settings.grpc_timeout_seconds
            )
            return message_to_json(response)
        except grpc.aio.AioRpcError as error:
            raise BackendCallError(map_grpc_failure(error.code(), error.details())) from error

    def _get_channel(self, target: str) -> grpc.aio.Channel:
        if target not in self._channels:
            self._channels[target] = grpc.aio.insecure_channel(target)
        return self._channels[target]

    @staticmethod
    async def _collect_stream(stream: Any, progress_reporter: ProgressReporter) -> dict[str, Any]:
        """Each streamed message becomes a progress notification; the last one is the result."""
        last_update: dict[str, Any] = {}
        update_count = 0
        async for update in stream:
            update_count += 1
            last_update = message_to_json(update)
            await progress_reporter.report(update_count, None, json.dumps(last_update))
        return last_update
