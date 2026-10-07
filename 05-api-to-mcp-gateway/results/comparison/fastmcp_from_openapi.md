# FastMCP.from_openapi vs the phase 5 gateway

fastmcp 4.0.11 on mcp 2.3.0; same orders OpenAPI document.

## FastMCP.from_openapi tools

| Tool | Arguments | Output schema |
|---|---|---|
| `cancelOrder` | order_id | True |
| `createOrder` | customer_email, customer_phone, items | True |
| `getCaller` |  | True |
| `getOrder` | order_id | True |
| `listOrders` | limit, status | True |

Resources / templates generated: 0

## Gateway tools

| Tool | Arguments | Output schema |
|---|---|---|
| `orders_cancel_order` | fields, order_id | True |
| `orders_create_order` | customer_email, customer_phone, fields, items | True |
| `orders_get_caller` | fields | True |
| `orders_get_order` | fields, order_id | True |
| `orders_list_orders` | fields, limit, status | True |

## Calls (FastMCP.from_openapi)

- getOrder(1): `{"is_error": false, "structured": {"id": 1, "status": "pending", "customer_email": "ana@example.com", "customer_phone": "+1 415 555 0100", "items": [{"sku": "SKU-001", "quantity": 2}], "total_cents": 3998, "created_at": "2026-10-07T19:47:43.144347Z"}, "text": "{\"id\":1,\"status\":\"pending\",\"customer_email\":\"ana@example.com\",\"customer_phone\":\"+1 415 555 0100\",\"items\":[{\"sku\":\"SKU-001\",\"quantity\":2}],\"total_cents\":3998,\"created_at\":\"2026-10-07T19:47:43.144347Z\"}"}`
- getOrder(999): `{"is_error": true, "structured": null, "text": "Error calling tool 'getOrder': HTTP error 404: Not Found - {'detail': 'order 999 not found'}"}`
