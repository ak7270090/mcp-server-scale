"""In-memory stock per SKU."""

from dataclasses import dataclass
from uuid import uuid4

LOW_STOCK_THRESHOLD = 5
SEED_STOCK = {"SKU-001": 25, "SKU-002": 3, "SKU-003": 0}
WAREHOUSE_BY_SKU = {"SKU-001": ("AMS1", "Amsterdam"), "SKU-002": ("BLR1", "Bengaluru")}
DEFAULT_WAREHOUSE = ("SFO1", "San Francisco")


class UnknownSkuError(LookupError):
    pass


class InsufficientStockError(ValueError):
    pass


@dataclass(frozen=True)
class StockSnapshot:
    sku: str
    available: int
    warehouse_code: str
    warehouse_city: str

    @property
    def status_name(self) -> str:
        if self.available == 0:
            return "OUT_OF_STOCK"
        if self.available <= LOW_STOCK_THRESHOLD:
            return "LOW_STOCK"
        return "IN_STOCK"


class StockStore:
    def __init__(self) -> None:
        self._available = dict(SEED_STOCK)

    def read(self, sku: str) -> StockSnapshot:
        if sku not in self._available:
            raise UnknownSkuError(f"unknown sku {sku!r}")
        warehouse_code, warehouse_city = WAREHOUSE_BY_SKU.get(sku, DEFAULT_WAREHOUSE)
        return StockSnapshot(sku, self._available[sku], warehouse_code, warehouse_city)

    def reserve(self, sku: str, quantity: int) -> tuple[str, int]:
        """Returns the reservation ID and the stock left."""
        snapshot = self.read(sku)
        if quantity > snapshot.available:
            raise InsufficientStockError(
                f"only {snapshot.available} of {sku} available, {quantity} requested"
            )
        self._available[sku] = snapshot.available - quantity
        return uuid4().hex, self._available[sku]
