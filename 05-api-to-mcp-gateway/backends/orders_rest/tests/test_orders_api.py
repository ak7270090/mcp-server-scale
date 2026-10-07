import pytest
from fastapi.testclient import TestClient

from ordersapi.app import create_orders_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_orders_app())


def test_gets_a_seeded_order(client: TestClient) -> None:
    response = client.get("/orders/1")

    assert response.status_code == 200
    assert response.json()["customer_email"] == "ana@example.com"
    assert response.json()["total_cents"] == 3998


def test_missing_order_is_404(client: TestClient) -> None:
    assert client.get("/orders/99").status_code == 404


def test_lists_orders_by_status(client: TestClient) -> None:
    shipped = client.get("/orders", params={"status": "shipped"}).json()

    assert [order["id"] for order in shipped] == [2]


def test_creates_an_order_with_total(client: TestClient) -> None:
    response = client.post(
        "/orders",
        json={
            "customer_email": "new@example.com",
            "customer_phone": "+1 555 0101",
            "items": [{"sku": "SKU-003", "quantity": 2}],
        },
    )

    assert response.status_code == 201
    assert response.json()["total_cents"] == 1798


def test_shipped_order_cannot_be_cancelled(client: TestClient) -> None:
    assert client.post("/orders/2/cancel").status_code == 409
    assert client.post("/orders/1/cancel").json()["status"] == "cancelled"


def test_caller_echoes_pass_through_headers(client: TestClient) -> None:
    response = client.get(
        "/caller", headers={"Authorization": "Bearer abc", "traceparent": "00-trace-span-01"}
    )

    assert response.json() == {"authorization": "Bearer abc", "traceparent": "00-trace-span-01"}


def test_operation_ids_are_explicit(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation_ids = {
        operation["operationId"] for path in spec["paths"].values() for operation in path.values()
    }

    assert operation_ids == {"getOrder", "listOrders", "createOrder", "cancelOrder", "getCaller"}
