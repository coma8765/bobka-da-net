-- Тестовые поставки продуктов категории Food
BEGIN;

INSERT INTO deliveries (
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
    (SELECT MIN(supplier_id) FROM suppliers WHERE is_active),
    p.product_id,
    (SELECT MIN(warehouse_id) FROM warehouses),
    TIMESTAMP '2026-09-11 12:00:00',
    10,
    ROUND(p.unit_price * 0.80, 2),
    'LAB2-' || LPAD(p.product_id::text, 6, '0'),
    'accepted',
    CASE WHEN p.is_perishable THEN DATE '2027-09-11' END
FROM products AS p
WHERE p.category = 'Food'
ORDER BY p.product_id
LIMIT 3
RETURNING delivery_id, product_id, quantity, unit_cost;

ROLLBACK;
