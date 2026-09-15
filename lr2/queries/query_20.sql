-- Удалённый тестовый товар
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
    'LAB2-DELETE-001',
    'Product for deletion',
    'Laboratory',
    'pcs',
    500.00,
    0.500,
    false,
    CURRENT_DATE
);

DELETE FROM products
WHERE sku = 'LAB2-DELETE-001'
RETURNING product_id, sku, name;

ROLLBACK;
