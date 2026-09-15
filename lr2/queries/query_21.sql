-- Удалённые товары без поставок
BEGIN;

DELETE FROM products AS p
WHERE NOT EXISTS (
    SELECT 1
    FROM deliveries AS d
    WHERE d.product_id = p.product_id
)
RETURNING p.product_id, p.sku, p.name;

ROLLBACK;
