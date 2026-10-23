\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS lr5;

DROP TABLE IF EXISTS lr5.delivery_documents;
DROP TABLE IF EXISTS lr5.deliveries_imported;

CREATE TABLE lr5.deliveries_imported
    (LIKE public.deliveries INCLUDING ALL);

ALTER TABLE lr5.deliveries_imported
    ADD CONSTRAINT deliveries_imported_supplier_fk
        FOREIGN KEY (supplier_id)
        REFERENCES public.suppliers (supplier_id),
    ADD CONSTRAINT deliveries_imported_product_fk
        FOREIGN KEY (product_id)
        REFERENCES public.products (product_id),
    ADD CONSTRAINT deliveries_imported_warehouse_fk
        FOREIGN KEY (warehouse_id)
        REFERENCES public.warehouses (warehouse_id);

CREATE TABLE lr5.delivery_documents (
    delivery_id bigint PRIMARY KEY
        REFERENCES public.deliveries (delivery_id),
    document jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT delivery_document_object_ck
        CHECK (jsonb_typeof(document) = 'object')
);

COMMENT ON TABLE lr5.deliveries_imported IS
    'Relational copy of public.deliveries restored from JSON Lines';
COMMENT ON TABLE lr5.delivery_documents IS
    'Nested JSONB snapshots of deliveries for LR5 JSON operations';

COMMIT;
