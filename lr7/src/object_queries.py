"""Пять запросов к обычным объектам: модуль не зависит от SQLAlchemy."""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Generic, Protocol, TypedDict, TypeVar


class SupplierLike(Protocol):
    supplier_id: int
    tax_id: str
    name: str
    rating: Decimal
    is_active: bool


class ProductLike(Protocol):
    sku: str
    unit_price: Decimal


class DeliveryLike(Protocol):
    delivery_id: int
    supplier_id: int
    warehouse_id: int
    quantity: int
    unit_cost: Decimal
    quality_status: str


class WarehouseLike(Protocol):
    warehouse_id: int
    code: str
    city: str


class DeliverySummary(TypedDict):
    count: int
    quantity: int
    total_cost: Decimal


SupplierT = TypeVar("SupplierT", bound=SupplierLike)
ProductT = TypeVar("ProductT", bound=ProductLike)


class SupplierCheck(TypedDict, Generic[SupplierT]):
    supplier: SupplierT
    has_rejected: bool


def select_active_suppliers(
    suppliers: Iterable[SupplierLike],
    min_rating: Decimal,
) -> list[tuple[str, str]]:
    return [
        (supplier.tax_id, supplier.name)
        for supplier in suppliers
        if supplier.is_active and supplier.rating >= min_rating
    ]


def top_products(products: Iterable[ProductT], limit: int) -> list[ProductT]:
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    return sorted(products, key=lambda product: (-product.unit_price, product.sku))[
        :limit
    ]


def summarize_deliveries(
    deliveries: Iterable[DeliveryLike],
) -> dict[str, DeliverySummary]:
    groups: defaultdict[str, DeliverySummary] = defaultdict(
        lambda: {"count": 0, "quantity": 0, "total_cost": Decimal(0)}
    )
    for delivery in deliveries:
        group = groups[delivery.quality_status]
        group["count"] += 1
        group["quantity"] += delivery.quantity
        group["total_cost"] += delivery.quantity * delivery.unit_cost
    return dict(sorted(groups.items()))


def join_deliveries_warehouses(
    deliveries: Iterable[DeliveryLike],
    warehouses: Iterable[WarehouseLike],
) -> list[tuple[int, str, str]]:
    by_id: defaultdict[int, list[WarehouseLike]] = defaultdict(list)
    for warehouse in warehouses:
        by_id[warehouse.warehouse_id].append(warehouse)
    return [
        (delivery.delivery_id, warehouse.code, warehouse.city)
        for delivery in deliveries
        for warehouse in by_id[delivery.warehouse_id]
    ]


def suppliers_with_valid_deliveries(
    suppliers: Iterable[SupplierT],
    deliveries: Iterable[DeliveryLike],
) -> list[SupplierCheck[SupplierT]]:
    by_supplier: defaultdict[int, list[DeliveryLike]] = defaultdict(list)
    for delivery in deliveries:
        by_supplier[delivery.supplier_id].append(delivery)
    result: list[SupplierCheck[SupplierT]] = []
    for supplier in suppliers:
        supplied = by_supplier[supplier.supplier_id]
        has_rejected = any(
            delivery.quality_status == "rejected" for delivery in supplied
        )
        if supplied and all(delivery.quantity > 0 for delivery in supplied):
            result.append({"supplier": supplier, "has_rejected": has_rejected})
    return result
