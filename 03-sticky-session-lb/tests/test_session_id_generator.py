import pytest
from starlette.testclient import TestClient

from mcpserver.app import create_asgi_app

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "unit-test", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def replica_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("MCP_REPLICA_ID", "mcp-replica-2")
    monkeypatch.delenv("MCP_OTEL_EXPORTER_ENDPOINT", raising=False)
    return TestClient(create_asgi_app())


def test_new_session_id_starts_with_replica_id(replica_client: TestClient) -> None:
    with replica_client:
        response = replica_client.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)

    session_id = response.headers["mcp-session-id"]
    assert response.status_code == 200
    assert session_id.startswith("mcp-replica-2.")
    assert len(session_id) > len("mcp-replica-2.")


def test_prefixed_session_id_is_accepted_on_later_requests(replica_client: TestClient) -> None:
    with replica_client:
        initialize_response = replica_client.post(
            "/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS
        )
        session_headers = {
            **MCP_HEADERS,
            "mcp-session-id": initialize_response.headers["mcp-session-id"],
            "mcp-protocol-version": "2025-11-25",
        }
        delete_response = replica_client.delete("/mcp", headers=session_headers)
        after_delete_response = replica_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=session_headers,
        )

    assert delete_response.status_code == 200
    assert after_delete_response.status_code == 404
