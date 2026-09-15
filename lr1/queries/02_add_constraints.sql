\set ON_ERROR_STOP on
\connect supply_lab

ALTER TABLE suppliers
    ADD CONSTRAINT suppliers_pk PRIMARY KEY (supplier_id),
    ADD CONSTRAINT suppliers_tax_id_uq UNIQUE (tax_id),
    ADD CONSTRAINT suppliers_email_uq UNIQUE (email),
    ADD CONSTRAINT suppliers_rating_ck CHECK (rating BETWEEN 1.00 AND 5.00);

ALTER TABLE products
    ADD CONSTRAINT products_pk PRIMARY KEY (product_id),
    ADD CONSTRAINT products_sku_uq UNIQUE (sku),
    ADD CONSTRAINT products_unit_price_ck CHECK (unit_price > 0),
    ADD CONSTRAINT products_weight_ck CHECK (weight_kg > 0);

ALTER TABLE warehouses
    ADD CONSTRAINT warehouses_pk PRIMARY KEY (warehouse_id),
    ADD CONSTRAINT warehouses_code_uq UNIQUE (code);

ALTER TABLE warehouse_sections
    ADD CONSTRAINT warehouse_sections_pk PRIMARY KEY (section_id),
    ADD CONSTRAINT warehouse_sections_location_uq UNIQUE (warehouse_id, section_id),
    ADD CONSTRAINT warehouse_sections_code_uq UNIQUE (warehouse_id, code),
    ADD CONSTRAINT warehouse_sections_warehouse_fk FOREIGN KEY (warehouse_id)
        REFERENCES warehouses (warehouse_id),
    ADD CONSTRAINT warehouse_sections_parent_fk
        FOREIGN KEY (warehouse_id, parent_section_id)
        REFERENCES warehouse_sections (warehouse_id, section_id),
    ADD CONSTRAINT warehouse_sections_not_self_ck
        CHECK (parent_section_id IS NULL OR parent_section_id <> section_id),
    ADD CONSTRAINT warehouse_sections_capacity_ck CHECK (capacity_m3 > 0),
    ADD CONSTRAINT warehouse_sections_floor_ck CHECK (floor >= 0),

    -- - `receiving` — приёмка товаров;
    -- - `storage` — обычное хранение;
    -- - `cold_storage` — хранение с температурным контролем;
    -- - `packing` — упаковка и комплектация;
    -- - `dispatch` — отгрузка товаров.
    ADD CONSTRAINT warehouse_sections_type_ck
        CHECK (section_type IN ('receiving', 'storage', 'cold_storage', 'packing', 'dispatch'));

ALTER TABLE deliveries
    ADD CONSTRAINT deliveries_pk PRIMARY KEY (delivery_id),
    ADD CONSTRAINT deliveries_business_key_uq
        UNIQUE (supplier_id, product_id, warehouse_id, batch_number),
    ADD CONSTRAINT deliveries_supplier_fk FOREIGN KEY (supplier_id)
        REFERENCES suppliers (supplier_id),
    ADD CONSTRAINT deliveries_product_fk FOREIGN KEY (product_id)
        REFERENCES products (product_id),
    ADD CONSTRAINT deliveries_warehouse_fk FOREIGN KEY (warehouse_id)
        REFERENCES warehouses (warehouse_id),
    ADD CONSTRAINT deliveries_quantity_ck CHECK (quantity > 0),
    ADD CONSTRAINT deliveries_unit_cost_ck CHECK (unit_cost > 0),
    ADD CONSTRAINT deliveries_quality_status_ck
        CHECK (quality_status IN ('accepted', 'inspection', 'rejected'));

CREATE INDEX deliveries_supplier_idx ON deliveries (supplier_id);
CREATE INDEX deliveries_product_idx ON deliveries (product_id);
CREATE INDEX deliveries_warehouse_idx ON deliveries (warehouse_id);
CREATE INDEX deliveries_delivered_at_idx ON deliveries (delivered_at);
CREATE INDEX warehouse_sections_parent_idx
    ON warehouse_sections (warehouse_id, parent_section_id);
