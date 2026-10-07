import pytest
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from starlette.testclient import TestClient

from mcpserver.app import create_asgi_app
from mcpserver.constants import HEALTH_CHECK_BODY, HEALTH_CHECK_PATH


def test_health_check_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_OTEL_EXPORTER_ENDPOINT", raising=False)

    with TestClient(create_asgi_app()) as client:
        response = client.get(HEALTH_CHECK_PATH)

    assert response.status_code == 200
    assert response.json() == HEALTH_CHECK_BODY


def test_tracing_is_off_without_exporter_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_OTEL_EXPORTER_ENDPOINT", raising=False)

    app = create_asgi_app()

    assert all(middleware.cls is not OpenTelemetryMiddleware for middleware in app.user_middleware)


def test_tracing_is_on_with_exporter_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_OTEL_EXPORTER_ENDPOINT", "http://localhost:4318")

    app = create_asgi_app()

    assert any(middleware.cls is OpenTelemetryMiddleware for middleware in app.user_middleware)


def test_request_without_session_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_OTEL_EXPORTER_ENDPOINT", raising=False)
    tools_list_request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    with TestClient(create_asgi_app()) as client:
        response = client.post(
            "/mcp",
            json=tools_list_request,
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 400
