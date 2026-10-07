"""Gateway overhead: the same order lookup directly over REST vs through the gateway over MCP.

Run one user class at a time, e.g.:
    locust -f load/locustfile.py --headless -u 20 -r 5 -t 60s DirectOrdersUser
    locust -f load/locustfile.py --headless -u 20 -r 5 -t 60s GatewayOrdersUser
"""

import itertools
import json
import os
from typing import Any

from locust import HttpUser, between, task

ORDERS_URL = os.environ.get("LOAD_ORDERS_URL", "http://localhost:8001")
GATEWAY_URL = os.environ.get("LOAD_GATEWAY_URL", "http://localhost:8000")
MCP_PATH = "/mcp"
ORDER_ID = 1
PROTOCOL_VERSION = "2025-11-25"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def read_jsonrpc_response(content_type: str, body: str, request_id: int) -> dict[str, Any] | None:
    if content_type.startswith("application/json"):
        return json.loads(body)
    for line in body.splitlines():
        if line.startswith("data:") and line[5:].strip():
            message = json.loads(line[5:])
            if message.get("id") == request_id:
                return message
    return None


class DirectOrdersUser(HttpUser):
    host = ORDERS_URL
    wait_time = between(0.1, 0.3)

    @task
    def get_order(self) -> None:
        self.client.get(f"/orders/{ORDER_ID}", name="REST GET /orders/{order_id}")


class GatewayOrdersUser(HttpUser):
    host = GATEWAY_URL
    wait_time = between(0.1, 0.3)

    def on_start(self) -> None:
        self._request_ids = itertools.count(1)
        self._session_headers = dict(MCP_HEADERS)
        initialize = {
            "jsonrpc": "2.0",
            "id": next(self._request_ids),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "phase5-load", "version": "1"},
            },
        }
        response = self.client.post(
            MCP_PATH, json=initialize, headers=self._session_headers, name="MCP initialize"
        )
        self._session_headers["mcp-session-id"] = response.headers["mcp-session-id"]
        self._session_headers["mcp-protocol-version"] = PROTOCOL_VERSION
        self.client.post(
            MCP_PATH,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._session_headers,
            name="MCP notifications/initialized",
        )

    def on_stop(self) -> None:
        self.client.delete(MCP_PATH, headers=self._session_headers, name="MCP DELETE session")

    @task
    def get_order(self) -> None:
        request_id = next(self._request_ids)
        call = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "orders_get_order", "arguments": {"order_id": ORDER_ID}},
        }
        with self.client.post(
            MCP_PATH,
            json=call,
            headers=self._session_headers,
            name="MCP tools/call orders_get_order",
            catch_response=True,
        ) as response:
            message = read_jsonrpc_response(
                response.headers.get("content-type", ""), response.text, request_id
            )
            if message is None or "error" in message or message["result"].get("isError"):
                response.failure(f"bad MCP response: {response.text[:200]}")
