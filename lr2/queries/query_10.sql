-- Товары с ценовой категорией
SELECT
    product_id,
    name,
    unit_price,
    CASE
        WHEN unit_price < 10000 THEN 'Недорогой'
        WHEN unit_price < 30000 THEN 'Средний'
        WHEN unit_price < 45000 THEN 'Дорогой'
        ELSE 'Очень дорогой'
    END AS price_category
FROM products
ORDER BY unit_price, product_id;
