"""Optional OpenTelemetry tracing: one span per HTTP request, tagged with replica and session."""

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from starlette.applications import Starlette

from mcpserver.config import ServerSettings
from mcpserver.constants import (
    SESSION_ID_HEADER,
    SPAN_ATTRIBUTE_SESSION_ID,
    TRACE_EXPORT_PATH,
    TRACE_SERVICE_NAME,
)


def add_session_id_to_span(span: trace.Span, scope: dict[str, Any]) -> None:
    for header_name, header_value in scope.get("headers", []):
        if header_name == SESSION_ID_HEADER:
            span.set_attribute(SPAN_ATTRIBUTE_SESSION_ID, header_value.decode())
            return


def enable_tracing(app: Starlette, settings: ServerSettings) -> None:
    """Export request spans over OTLP/HTTP when an exporter endpoint is configured."""
    if not settings.otel_exporter_endpoint:
        return
    resource = Resource.create(
        {SERVICE_NAME: TRACE_SERVICE_NAME, SERVICE_INSTANCE_ID: settings.replica_id}
    )
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(
        endpoint=f"{settings.otel_exporter_endpoint}{TRACE_EXPORT_PATH}"
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)
    app.add_middleware(OpenTelemetryMiddleware, server_request_hook=add_session_id_to_span)
