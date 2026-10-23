"""Atomically restore a JSON Lines export into lr5.deliveries_imported."""

from pathlib import Path

import psycopg

try:
    from .db import DELIVERIES_FILE, connection_parameters
except ImportError:
    from db import DELIVERIES_FILE, connection_parameters


REQUIRED_KEYS = (
    "delivery_id",
    "supplier_id",
    "product_id",
    "warehouse_id",
    "delivered_at",
    "quantity",
    "unit_cost",
    "batch_number",
    "quality_status",
    "expires_on",
)

VALIDATE_DOCUMENTS_SQL = """
SELECT
    count(*) FILTER (
        WHERE jsonb_typeof(payload) <> 'object'
    ) AS non_object_count,
    count(*) FILTER (
        WHERE NOT (payload ?& %(required_keys)s::text[])
    ) AS missing_key_count
FROM raw_delivery_json
"""

INSERT_DOCUMENTS_SQL = """
TRUNCATE TABLE lr5.deliveries_imported;

INSERT INTO lr5.deliveries_imported (
    delivery_id,
    supplier_id,
    product_id,
    warehouse_id,
    delivered_at,
    quantity,
    unit_cost,
    batch_number,
    quality_status,
    expires_on
)
SELECT
    record.delivery_id,
    record.supplier_id,
    record.product_id,
    record.warehouse_id,
    record.delivered_at,
    record.quantity,
    record.unit_cost,
    record.batch_number,
    record.quality_status,
    record.expires_on
FROM raw_delivery_json AS raw
CROSS JOIN LATERAL jsonb_to_record(raw.payload) AS record(
    delivery_id bigint,
    supplier_id bigint,
    product_id bigint,
    warehouse_id bigint,
    delivered_at timestamp without time zone,
    quantity integer,
    unit_cost numeric(12, 2),
    batch_number varchar(20),
    quality_status varchar(16),
    expires_on date
);
"""

VERIFY_ROUND_TRIP_SQL = """
DO $verification$
DECLARE
    source_count bigint;
    raw_count bigint;
    imported_count bigint;
BEGIN
    SELECT count(*) INTO source_count FROM public.deliveries;
    SELECT count(*) INTO raw_count FROM raw_delivery_json;
    SELECT count(*) INTO imported_count FROM lr5.deliveries_imported;

    IF raw_count <> source_count OR imported_count <> source_count THEN
        RAISE EXCEPTION
            'Row count mismatch: source %, JSONL %, imported %',
            source_count,
            raw_count,
            imported_count;
    END IF;

    IF EXISTS (
        SELECT
            delivery_id,
            supplier_id,
            product_id,
            warehouse_id,
            delivered_at,
            quantity,
            unit_cost,
            batch_number,
            quality_status,
            expires_on
        FROM public.deliveries
        EXCEPT
        SELECT
            delivery_id,
            supplier_id,
            product_id,
            warehouse_id,
            delivered_at,
            quantity,
            unit_cost,
            batch_number,
            quality_status,
            expires_on
        FROM lr5.deliveries_imported
    ) OR EXISTS (
        SELECT
            delivery_id,
            supplier_id,
            product_id,
            warehouse_id,
            delivered_at,
            quantity,
            unit_cost,
            batch_number,
            quality_status,
            expires_on
        FROM lr5.deliveries_imported
        EXCEPT
        SELECT
            delivery_id,
            supplier_id,
            product_id,
            warehouse_id,
            delivered_at,
            quantity,
            unit_cost,
            batch_number,
            quality_status,
            expires_on
        FROM public.deliveries
    ) THEN
        RAISE EXCEPTION 'Imported deliveries differ from public.deliveries';
    END IF;
END
$verification$;
"""


def import_deliveries(source: Path = DELIVERIES_FILE) -> int:
    """Import *source* in one transaction and return its record count."""

    source = Path(source)
    imported_rows = 0

    with source.open("r", encoding="utf-8", newline="") as input_file:
        with psycopg.connect(**connection_parameters()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TEMP TABLE raw_delivery_json (
                        payload jsonb NOT NULL
                    ) ON COMMIT DROP
                    """
                )

                with cursor.copy(
                    "COPY raw_delivery_json (payload) FROM STDIN"
                ) as copy:
                    for line_number, source_line in enumerate(input_file, start=1):
                        payload = source_line.rstrip("\r\n")
                        if not payload.strip():
                            raise ValueError(
                                f"Empty JSONL record at line {line_number}"
                            )
                        copy.write_row((payload,))
                        imported_rows += 1

                validation_result = cursor.execute(
                    VALIDATE_DOCUMENTS_SQL,
                    {"required_keys": list(REQUIRED_KEYS)},
                ).fetchone()
                non_object_count, missing_key_count = validation_result
                if non_object_count:
                    raise ValueError("Every JSONL record must be a JSON object")
                if missing_key_count:
                    raise ValueError(
                        "A JSONL record does not contain all delivery keys"
                    )

                cursor.execute(INSERT_DOCUMENTS_SQL)
                cursor.execute(VERIFY_ROUND_TRIP_SQL)

    return imported_rows


def main() -> None:
    imported_rows = import_deliveries()
    print(f"Imported and verified {imported_rows} deliveries from {DELIVERIES_FILE}")


if __name__ == "__main__":
    main()
