"""SQLAlchemy-запросы с явными границами транзакций."""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypedDict, cast

from sqlalchemy import Select, delete, insert, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from .models import Delivery, DeliveryTag, Product, Supplier, Warehouse


class Collections(TypedDict):
    suppliers: list[Supplier]
    products: list[Product]
    warehouses: list[Warehouse]
    deliveries: list[Delivery]


class DeliveryDetails(TypedDict):
    delivery_id: int
    delivered_at: datetime
    quantity: int
    unit_cost: Decimal
    quality_status: str
    tax_id: str
    supplier_name: str
    sku: str
    product_name: str
    warehouse_code: str
    warehouse_city: str
    total_cost: Decimal


DeliveryDetailsRow = tuple[
    int, datetime, int, Decimal, str, str, str, str, str, str, str, Decimal
]


def products_statement(
    category: str,
    min_price: Decimal,
    limit: int,
) -> Select[tuple[Product]]:
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    return (
        select(Product)
        .where(Product.category == category, Product.unit_price >= min_price)
        .order_by(Product.unit_price.desc(), Product.sku)
        .limit(limit)
    )


def delivery_details_statement() -> Select[DeliveryDetailsRow]:
    return (
        select(
            Delivery.delivery_id,
            Delivery.delivered_at,
            Delivery.quantity,
            Delivery.unit_cost,
            Delivery.quality_status,
            Supplier.tax_id,
            Supplier.name.label("supplier_name"),
            Product.sku,
            Product.name.label("product_name"),
            Warehouse.code.label("warehouse_code"),
            Warehouse.city.label("warehouse_city"),
            (Delivery.quantity * Delivery.unit_cost).label("total_cost"),
        )
        .select_from(Delivery)
        .join(Delivery.supplier)
        .join(Delivery.product)
        .join(Delivery.warehouse)
        .order_by(Delivery.delivery_id)
    )


class Repository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def select_products(
        self, category: str, min_price: Decimal, limit: int
    ) -> list[Product]:
        statement = products_statement(category, min_price, limit)
        with self.sessions() as session, session.begin():
            return list(session.scalars(statement))

    def select_delivery_details(
        self,
        date_from: date | datetime,
        date_to: date | datetime,
    ) -> list[DeliveryDetails]:
        if date_from > date_to:
            raise ValueError("date_from must not exceed date_to")
        statement = delivery_details_statement().where(
            Delivery.delivered_at >= date_from,
            Delivery.delivered_at < date_to,
        )
        with self.sessions() as session, session.begin():
            return [
                cast(DeliveryDetails, dict(row))
                for row in session.execute(statement).mappings()
            ]

    def load_collections(self) -> Collections:
        """Материализация для пяти запросов в памяти; связи не загружаются."""
        with self.sessions() as session, session.begin():
            return {
                "suppliers": list(
                    session.scalars(select(Supplier).order_by(Supplier.supplier_id))
                ),
                "products": list(
                    session.scalars(select(Product).order_by(Product.product_id))
                ),
                "warehouses": list(
                    session.scalars(select(Warehouse).order_by(Warehouse.warehouse_id))
                ),
                "deliveries": list(
                    session.scalars(select(Delivery).order_by(Delivery.delivery_id))
                ),
            }

    def insert_delivery_tag(self, delivery_id: int, tag: str) -> int:
        statement = (
            insert(DeliveryTag)
            .values(delivery_id=delivery_id, tag=tag)
            .returning(DeliveryTag.tag_id)
        )
        with self.sessions() as session, session.begin():
            return session.execute(statement).scalar_one()

    def rename_delivery_tag(self, tag_id: int, new_tag: str) -> int:
        statement = (
            update(DeliveryTag)
            .where(DeliveryTag.tag_id == tag_id)
            .values(tag=new_tag)
            .returning(DeliveryTag.tag_id)
        )
        with self.sessions() as session, session.begin():
            return session.execute(statement).scalar_one()

    def delete_delivery_tag(self, tag_id: int) -> int:
        statement = (
            delete(DeliveryTag)
            .where(DeliveryTag.tag_id == tag_id)
            .returning(DeliveryTag.tag_id)
        )
        with self.sessions() as session, session.begin():
            return session.execute(statement).scalar_one()

    def describe_table_via_procedure(self, table_name: str) -> dict[str, Any]:
        with self.sessions() as session, session.begin():
            metadata = session.execute(
                text("CALL public.sp_describe_table(:table_name, NULL::jsonb)"),
                {"table_name": table_name},
            ).scalar_one()
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if not isinstance(metadata, dict):
                raise TypeError("Procedure must return a JSON object")
            return metadata
