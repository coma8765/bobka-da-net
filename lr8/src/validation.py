"""Shared whole-file contract; no database access or third-party modules."""

import datetime as dt
import decimal
import json
import re
import uuid

UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
FILENAME = re.compile(
    rf"(?P<file_id>{UUID4})__delivery_events__(?P<formed_at>[0-9]{{8}}T[0-9]{{6}}Z)\.json"
)
FIELDS = {
    "event_id",
    "source_file_id",
    "supplier_tax_id",
    "product_sku",
    "warehouse_code",
    "delivered_at",
    "quantity",
    "unit_cost",
    "batch_number",
    "quality_status",
    "expires_on",
}
STATUSES = ("accepted", "inspection", "rejected")
MAX_BYTES = 1024 * 1024


def parse_filename(filename):
    match = FILENAME.fullmatch(filename)
    if not match:
        raise ValueError("invalid_filename: expected UUID4__delivery_events__UTC.json")
    dt.datetime.strptime(match["formed_at"], "%Y%m%dT%H%M%SZ")
    return match.groupdict()


def reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def decode_json(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("file exceeds 1 MiB")
    return json.loads(
        raw.decode("utf-8"),
        parse_float=decimal.Decimal,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def validate_records(records, filename):
    metadata = parse_filename(filename)
    if not isinstance(records, list) or not 1 <= len(records) <= 20:
        raise ValueError("root must be an array containing 1..20 records")
    events, batches = set(), set()
    for index, row in enumerate(records):
        prefix = f"record {index}: "
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError(prefix + "missing or unknown fields")
        for field, limit in (
            ("supplier_tax_id", 12),
            ("product_sku", 20),
            ("warehouse_code", 16),
            ("batch_number", 40),
        ):
            value = row[field]
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or "\x00" in value
            ):
                raise ValueError(prefix + f"invalid {field}")
        for field in ("event_id", "source_file_id"):
            value = row[field]
            if not isinstance(value, str):
                raise ValueError(prefix + f"invalid {field}")
            try:
                valid_uuid = str(uuid.UUID(value)) == value
            except ValueError:
                valid_uuid = False
            if not valid_uuid:
                raise ValueError(prefix + f"invalid {field}")
        if row["source_file_id"] != metadata["file_id"]:
            raise ValueError(prefix + "source_file_id does not match filename")
        if row["event_id"] in events or row["batch_number"] in batches:
            raise ValueError(prefix + "duplicate event_id or batch_number")
        events.add(row["event_id"])
        batches.add(row["batch_number"])
        if type(row["quantity"]) is not int or not 0 < row["quantity"] <= 2147483647:
            raise ValueError(prefix + "quantity must be a positive PostgreSQL integer")
        price = row["unit_cost"]
        if isinstance(price, bool) or not isinstance(
            price, (int, float, decimal.Decimal)
        ):
            raise ValueError(prefix + "unit_cost must be numeric")
        price = decimal.Decimal(str(price))
        if not price.is_finite() or not 0 < price <= decimal.Decimal("9999999999.99"):
            raise ValueError(prefix + "unit_cost outside numeric(12,2)")
        if price != price.quantize(decimal.Decimal("0.01")):
            raise ValueError(prefix + "unit_cost has more than two decimal places")
        if row["quality_status"] not in STATUSES:
            raise ValueError(prefix + "unknown quality_status")
        delivered = row["delivered_at"]
        if not isinstance(delivered, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", delivered
        ):
            raise ValueError(prefix + "delivered_at must be UTC ISO timestamp")
        dt.datetime.strptime(delivered, "%Y-%m-%dT%H:%M:%SZ")
        expires = row["expires_on"]
        if expires is not None:
            if not isinstance(expires, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", expires
            ):
                raise ValueError(prefix + "expires_on must be ISO date or null")
            dt.date.fromisoformat(expires)
    return metadata
