"""FastAPI routes. ``operation_id`` values become the MCP tool names (``orders_<snake_case>``)."""

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, status

from ordersapi.order_store import OrderNotCancellableError, OrderNotFoundError, OrderStore
from ordersapi.schemas import CallerInfo, CreateOrderRequest, ErrorDetail, Order, OrderStatus

NOT_FOUND_RESPONSE = {status.HTTP_404_NOT_FOUND: {"model": ErrorDetail}}


def create_orders_app() -> FastAPI:
    order_store = OrderStore()
    order_store.seed()
    app = FastAPI(title="Orders API", version="1.0.0")
    app.state.order_store = order_store
    OrdersRoutes(order_store).register(app)
    return app


class OrdersRoutes:
    def __init__(self, order_store: OrderStore) -> None:
        self._order_store = order_store

    def register(self, app: FastAPI) -> None:
        app.get(
            "/orders/{order_id}",
            operation_id="getOrder",
            summary="Get one order by its ID.",
            responses=NOT_FOUND_RESPONSE,
        )(self.get_order)
        app.get("/orders", operation_id="listOrders", summary="List orders, newest last.")(
            self.list_orders
        )
        app.post(
            "/orders",
            operation_id="createOrder",
            summary="Create an order.",
            status_code=status.HTTP_201_CREATED,
        )(self.create_order)
        app.post(
            "/orders/{order_id}/cancel",
            operation_id="cancelOrder",
            summary="Cancel an order that has not shipped.",
            responses={**NOT_FOUND_RESPONSE, status.HTTP_409_CONFLICT: {"model": ErrorDetail}},
        )(self.cancel_order)
        app.get(
            "/caller",
            operation_id="getCaller",
            summary="Show the Authorization and traceparent headers this service received.",
        )(self.get_caller)
        app.get("/healthz", include_in_schema=False)(self.report_health)

    async def get_order(self, order_id: int) -> Order:
        try:
            return self._order_store.get(order_id)
        except OrderNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    async def list_orders(
        self,
        order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> list[Order]:
        return self._order_store.list(order_status, limit)

    async def create_order(self, request: CreateOrderRequest) -> Order:
        return self._order_store.create(request)

    async def cancel_order(self, order_id: int) -> Order:
        try:
            return self._order_store.cancel(order_id)
        except OrderNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except OrderNotCancellableError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    async def get_caller(
        self,
        authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
        traceparent: Annotated[str | None, Header(include_in_schema=False)] = None,
    ) -> CallerInfo:
        return CallerInfo(authorization=authorization, traceparent=traceparent)

    async def report_health(self) -> dict[str, str]:
        return {"status": "ok"}
