"""Отображение таблиц lr1 и собственной таблицы lr7 без создания схемы."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class QualityStatus(StrEnum):
    ACCEPTED = "accepted"
    INSPECTION = "inspection"
    REJECTED = "rejected"


class Base(DeclarativeBase):
    pass


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1.00 AND 5.00", name="suppliers_rating_ck"),
        {"schema": "public"},
    )

    supplier_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    tax_id: Mapped[str] = mapped_column(String(12), unique=True)
    country: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    phone: Mapped[str] = mapped_column(String(24))
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    is_active: Mapped[bool]
    created_at: Mapped[date]


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit_price > 0", name="products_unit_price_ck"),
        CheckConstraint("weight_kg > 0", name="products_weight_ck"),
        {"schema": "public"},
    )

    product_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(12))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    is_perishable: Mapped[bool]
    created_at: Mapped[date]


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = ({"schema": "public"},)

    warehouse_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    country: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(240))
    opened_on: Mapped[date]


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint(
            "supplier_id",
            "product_id",
            "warehouse_id",
            "batch_number",
            name="deliveries_business_key_uq",
        ),
        CheckConstraint("quantity > 0", name="deliveries_quantity_ck"),
        CheckConstraint("unit_cost > 0", name="deliveries_unit_cost_ck"),
        CheckConstraint(
            "quality_status IN ('accepted', 'inspection', 'rejected')",
            name="deliveries_quality_status_ck",
        ),
        {"schema": "public"},
    )

    delivery_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("public.suppliers.supplier_id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("public.products.product_id"))
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("public.warehouses.warehouse_id")
    )
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    quantity: Mapped[int]
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    batch_number: Mapped[str] = mapped_column(String(20))
    quality_status: Mapped[str] = mapped_column(String(16))
    expires_on: Mapped[date | None]

    supplier: Mapped[Supplier] = relationship(lazy="raise")
    product: Mapped[Product] = relationship(lazy="raise")
    warehouse: Mapped[Warehouse] = relationship(lazy="raise")


class DeliveryTag(Base):
    __tablename__ = "delivery_tags"
    __table_args__ = (
        UniqueConstraint("delivery_id", "tag", name="delivery_tags_uq"),
        CheckConstraint("btrim(tag) <> ''"),
        {"schema": "lr7"},
    )

    tag_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("public.deliveries.delivery_id", ondelete="CASCADE")
    )
    tag: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
