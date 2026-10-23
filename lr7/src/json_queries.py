import json
import os
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypedDict, cast

from sqlalchemy.orm import Session, sessionmaker

from .models import QualityStatus
from .repository import delivery_details_statement


class SupplierJSON(TypedDict):
    tax_id: str
    name: str


class ProductJSON(TypedDict):
    sku: str
    name: str


class WarehouseJSON(TypedDict):
    code: str
    city: str


class DeliveryJSON(TypedDict):
    delivery_id: int
    supplier: SupplierJSON
    product: ProductJSON
    warehouse: WarehouseJSON
    quantity: int
    unit_cost: str
    quality_status: str
    tags: list[str]


class DeliveryDocument(TypedDict):
    schema_version: int
    generated_at: str
    deliveries: list[DeliveryJSON]


class DeliveryProjection(TypedDict):
    delivery_id: int
    supplier_name: str
    product_name: str
    warehouse_code: str
    quantity: int
    total_cost: Decimal


def serialize_status(value: str) -> str:
    return QualityStatus(value).value


def serialize_decimal(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Expected a finite Decimal")
    return format(value, "f")


def serialize_date(value: date) -> str:
    if not isinstance(value, date):
        raise TypeError("Expected date or datetime")
    result = value.isoformat()
    if isinstance(value, datetime) and value.utcoffset() is not None:
        result = value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return result


def json_default(value: object) -> str:
    if isinstance(value, QualityStatus):
        return serialize_status(value)
    if isinstance(value, Decimal):
        return serialize_decimal(value)
    if isinstance(value, date):
        return serialize_date(value)
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def _validate_delivery(delivery: object) -> None:
    if not isinstance(delivery, dict):
        raise ValueError("Delivery must be an object")
    required = {
        "delivery_id",
        "supplier",
        "product",
        "warehouse",
        "quantity",
        "unit_cost",
        "quality_status",
        "tags",
    }
    if not required <= delivery.keys():
        raise ValueError("Missing mandatory delivery fields")
    for field in ("delivery_id", "quantity"):
        if type(delivery[field]) is not int or delivery[field] <= 0:
            raise ValueError(f"{field} must be a positive integer")
    for field, keys in (
        ("supplier", ("tax_id", "name")),
        ("product", ("sku", "name")),
        ("warehouse", ("code", "city")),
    ):
        nested = delivery[field]
        if not isinstance(nested, dict) or any(
            not isinstance(nested.get(key), str) or not nested[key].strip()
            for key in keys
        ):
            raise ValueError(f"Invalid {field}")
    if not isinstance(delivery["unit_cost"], str):
        raise ValueError("unit_cost must be a decimal string")
    try:
        cost = Decimal(delivery["unit_cost"])
    except InvalidOperation as error:
        raise ValueError("Invalid unit_cost") from error
    if not cost.is_finite() or cost <= 0:
        raise ValueError("unit_cost must be finite and positive")
    serialize_status(delivery["quality_status"])
    tags = delivery["tags"]
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not tag.strip() or len(tag) > 40 for tag in tags
    ):
        raise ValueError(
            "tags must be an array of nonempty strings of at most 40 characters"
        )


def _validate_document(document: object) -> DeliveryDocument:
    if not isinstance(document, dict):
        raise ValueError("Document must be an object")
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
    ):
        raise ValueError("Unsupported schema_version")
    generated_at = document.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("generated_at must be an ISO datetime")
    if datetime.fromisoformat(generated_at).utcoffset() is None:
        raise ValueError("generated_at must include a timezone")
    deliveries = document.get("deliveries")
    if not isinstance(deliveries, list):
        raise ValueError("deliveries must be an array")
    seen = set()
    for delivery in deliveries:
        _validate_delivery(delivery)
        delivery_id = delivery["delivery_id"]
        if delivery_id in seen:
            raise ValueError(f"Duplicate delivery_id: {delivery_id}")
        seen.add(delivery_id)
    return cast(DeliveryDocument, document)


def _load(path: str | Path) -> DeliveryDocument:
    with Path(path).open(encoding="utf-8") as stream:
        return _validate_document(json.load(stream))


def _write_atomic(path: str | Path, document: DeliveryDocument) -> None:
    _validate_document(document)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                document,
                stream,
                ensure_ascii=False,
                indent=2,
                default=json_default,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _load(temporary)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_json(sessions: sessionmaker[Session], path: str | Path) -> DeliveryDocument:
    """Экспортирует четыре исходные таблицы одним SELECT; tags — локальные JSON-теги."""
    with sessions() as session, session.begin():
        rows = session.execute(delivery_details_statement()).mappings().all()
    deliveries: list[DeliveryJSON] = [
        {
            "delivery_id": row["delivery_id"],
            "supplier": {"tax_id": row["tax_id"], "name": row["supplier_name"]},
            "product": {"sku": row["sku"], "name": row["product_name"]},
            "warehouse": {"code": row["warehouse_code"], "city": row["warehouse_city"]},
            "quantity": row["quantity"],
            "unit_cost": serialize_decimal(row["unit_cost"]),
            "quality_status": serialize_status(row["quality_status"]),
            "tags": [],
        }
        for row in rows
    ]
    document: DeliveryDocument = {
        "schema_version": 1,
        "generated_at": serialize_date(datetime.now(timezone.utc)),
        "deliveries": deliveries,
    }
    _write_atomic(path, document)
    return document


def read_json(path: str | Path, status: str) -> list[DeliveryProjection]:
    status = serialize_status(status)
    document = _load(path)
    return [
        {
            "delivery_id": delivery["delivery_id"],
            "supplier_name": delivery["supplier"]["name"],
            "product_name": delivery["product"]["name"],
            "warehouse_code": delivery["warehouse"]["code"],
            "quantity": delivery["quantity"],
            "total_cost": delivery["quantity"] * Decimal(delivery["unit_cost"]),
        }
        for delivery in sorted(
            document["deliveries"], key=lambda row: row["delivery_id"]
        )
        if delivery["quality_status"] == status
    ]


def update_json(path: str | Path, delivery_id: int, status: str) -> None:
    status = serialize_status(status)
    if type(delivery_id) is not int:
        raise ValueError("delivery_id must be an integer")
    document = _load(path)
    matches = [
        row for row in document["deliveries"] if row["delivery_id"] == delivery_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one delivery: {delivery_id}")
    matches[0]["quality_status"] = status
    _write_atomic(path, document)


def append_json(path: str | Path, delivery: DeliveryJSON) -> None:
    _validate_delivery(delivery)
    document = _load(path)
    if any(
        row["delivery_id"] == delivery["delivery_id"] for row in document["deliveries"]
    ):
        raise ValueError(f"Duplicate delivery_id: {delivery['delivery_id']}")
    document["deliveries"].append(delivery)
    _write_atomic(path, document)
