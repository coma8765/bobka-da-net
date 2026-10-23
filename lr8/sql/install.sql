\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA IF NOT EXISTS lr8;
CREATE TABLE IF NOT EXISTS lr8.delivery_events (
    event_id uuid PRIMARY KEY,
    source_file_id uuid NOT NULL,
    supplier_tax_id varchar(12) NOT NULL CHECK (btrim(supplier_tax_id) <> ''),
    product_sku varchar(20) NOT NULL CHECK (btrim(product_sku) <> ''),
    warehouse_code varchar(16) NOT NULL CHECK (btrim(warehouse_code) <> ''),
    delivered_at timestamp with time zone NOT NULL,
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_cost numeric(12, 2) NOT NULL CHECK (unit_cost > 0 AND unit_cost <> 'NaN'),
    batch_number varchar(40) NOT NULL UNIQUE CHECK (btrim(batch_number) <> ''),
    quality_status varchar(16) NOT NULL
        CHECK (quality_status IN ('accepted', 'inspection', 'rejected')),
    expires_on date,
    loaded_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_file_id, event_id)
);
COMMIT;
