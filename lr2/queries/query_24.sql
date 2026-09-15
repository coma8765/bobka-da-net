-- Ценовая статистика поставок каждого товара
SELECT
    d.delivery_id,
    d.product_id,
    p.name,
    d.unit_cost,
    ROUND(AVG(d.unit_cost) OVER (PARTITION BY d.product_id), 2) AS average_cost,
    MIN(d.unit_cost) OVER (PARTITION BY d.product_id) AS minimum_cost,
    MAX(d.unit_cost) OVER (PARTITION BY d.product_id) AS maximum_cost
FROM deliveries AS d
JOIN products AS p ON p.product_id = d.product_id
ORDER BY d.product_id, d.delivery_id
LIMIT 100;
