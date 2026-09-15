-- Вставленный тестовый товар
BEGIN;

INSERT INTO products (
    sku,
    name,
    category,
    unit,
    unit_price,
    weight_kg,
    is_perishable,
    created_at
)
VALUES (
    'LAB2-INSERT-001',
    'Laboratory product',
    'Laboratory',
    'pcs',
    1000.00,
    1.000,
    false,
    CURRENT_DATE
)
RETURNING product_id, sku, name;

ROLLBACK;
