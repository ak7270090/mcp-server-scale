"""In-memory orders with a few seeded records."""

from datetime import UTC, datetime

from ordersapi.schemas import CreateOrderRequest, Order, OrderItem, OrderStatus

UNIT_PRICE_CENTS = {"SKU-001": 1999, "SKU-002": 4500, "SKU-003": 899}
DEFAULT_UNIT_PRICE_CENTS = 1000


class OrderNotFoundError(LookupError):
    pass


class OrderNotCancellableError(ValueError):
    pass


def calculate_total_cents(items: list[OrderItem]) -> int:
    return sum(
        UNIT_PRICE_CENTS.get(item.sku, DEFAULT_UNIT_PRICE_CENTS) * item.quantity for item in items
    )


class OrderStore:
    def __init__(self) -> None:
        self._orders: dict[int, Order] = {}
        self._next_id = 1

    def seed(self) -> None:
        self.create(
            CreateOrderRequest(
                customer_email="ana@example.com",
                customer_phone="+1 415 555 0100",
                items=[OrderItem(sku="SKU-001", quantity=2)],
            )
        )
        shipped = self.create(
            CreateOrderRequest(
                customer_email="raj@example.com",
                customer_phone="+44 20 7946 0958",
                items=[OrderItem(sku="SKU-002", quantity=1), OrderItem(sku="SKU-003", quantity=3)],
            )
        )
        self._orders[shipped.id] = shipped.model_copy(update={"status": OrderStatus.SHIPPED})

    def create(self, request: CreateOrderRequest) -> Order:
        order = Order(
            id=self._next_id,
            status=OrderStatus.PENDING,
            customer_email=request.customer_email,
            customer_phone=request.customer_phone,
            items=request.items,
            total_cents=calculate_total_cents(request.items),
            created_at=datetime.now(UTC),
        )
        self._orders[order.id] = order
        self._next_id += 1
        return order

    def get(self, order_id: int) -> Order:
        if order_id not in self._orders:
            raise OrderNotFoundError(f"order {order_id} not found")
        return self._orders[order_id]

    def list(self, status: OrderStatus | None, limit: int) -> list[Order]:
        matching = [order for order in self._orders.values() if status in (None, order.status)]
        return matching[:limit]

    def cancel(self, order_id: int) -> Order:
        order = self.get(order_id)
        if order.status == OrderStatus.SHIPPED:
            raise OrderNotCancellableError(f"order {order_id} has already shipped")
        cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED})
        self._orders[order_id] = cancelled
        return cancelled
