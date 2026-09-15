-- Товары с заданным фрагментом названия
SELECT product_id, sku, name, category
FROM products
WHERE name LIKE '%product 01%'
ORDER BY product_id;
