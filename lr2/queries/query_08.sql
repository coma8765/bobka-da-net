-- Цены товаров и статистика поставок
SELECT
    p.product_id,
    p.name,
    p.unit_price,
    (
        SELECT ROUND(AVG(d.unit_cost), 2)
        FROM deliveries AS d
        WHERE d.product_id = p.product_id
    ) AS average_delivery_cost,
    (
        SELECT MIN(d.unit_cost)
        FROM deliveries AS d
        WHERE d.product_id = p.product_id
    ) AS minimum_delivery_cost
FROM products AS p
WHERE p.category = 'Food'
ORDER BY p.product_id;
