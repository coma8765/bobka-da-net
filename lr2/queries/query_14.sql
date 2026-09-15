-- Статистика закупочных цен товаров Food
SELECT
    p.product_id,
    p.name,
    p.unit_price,
    ROUND(AVG(d.unit_cost), 2) AS average_delivery_cost,
    MIN(d.unit_cost) AS minimum_delivery_cost
FROM products AS p
LEFT JOIN deliveries AS d ON d.product_id = p.product_id
WHERE p.category = 'Food'
GROUP BY p.product_id, p.name, p.unit_price
ORDER BY p.product_id;
