-- Товар с усреднённой закупочной ценой
BEGIN;

UPDATE products AS p
SET unit_price = (
    SELECT ROUND(AVG(d.unit_cost), 2)
    FROM deliveries AS d
    WHERE d.product_id = p.product_id
)
WHERE p.product_id = (
    SELECT MIN(product_id)
    FROM deliveries
)
RETURNING p.product_id, p.name, p.unit_price;

ROLLBACK;
