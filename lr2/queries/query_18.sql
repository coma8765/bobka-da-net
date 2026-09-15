-- Товар с увеличенной ценой
BEGIN;

UPDATE products
SET unit_price = ROUND(unit_price * 1.05, 2)
WHERE product_id = 1
RETURNING product_id, name, unit_price;

ROLLBACK;
