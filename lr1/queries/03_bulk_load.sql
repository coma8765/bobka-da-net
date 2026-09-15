\set ON_ERROR_STOP on
\connect supply_lab

BEGIN;

TRUNCATE TABLE
    deliveries,
    warehouse_sections,
    products,
    suppliers,
    warehouses
RESTART IDENTITY;

\copy suppliers (name, tax_id, country, city, email, phone, rating, is_active, created_at) FROM 'data/suppliers.csv' WITH (FORMAT csv, HEADER true)
\copy products (sku, name, category, unit, unit_price, weight_kg, is_perishable, created_at) FROM 'data/products.csv' WITH (FORMAT csv, HEADER true)
\copy warehouses (code, name, country, city, address, opened_on) FROM 'data/warehouses.csv' WITH (FORMAT csv, HEADER true)
\copy warehouse_sections (warehouse_id, parent_section_id, code, name, section_type, capacity_m3, floor, is_active) FROM 'data/warehouse_sections.csv' WITH (FORMAT csv, HEADER true, NULL '')
\copy deliveries (supplier_id, product_id, warehouse_id, delivered_at, quantity, unit_cost, batch_number, quality_status, expires_on) FROM 'data/deliveries.csv' WITH (FORMAT csv, HEADER true, NULL '')

COMMIT;

ANALYZE suppliers;
ANALYZE products;
ANALYZE warehouses;
ANALYZE warehouse_sections;
ANALYZE deliveries;
