-- Лидеры по количеству и стоимости поставок
SELECT criterion, product_id, product_name, metric
FROM (
    SELECT
        'Количество' AS criterion,
        p.product_id,
        p.name AS product_name,
        SUM(d.quantity)::numeric AS metric
    FROM products AS p
    JOIN deliveries AS d ON d.product_id = p.product_id
    GROUP BY p.product_id, p.name
    ORDER BY metric DESC, p.product_id
    LIMIT 1
) AS quantity_leader
UNION ALL
SELECT criterion, product_id, product_name, metric
FROM (
    SELECT
        'Стоимость' AS criterion,
        p.product_id,
        p.name AS product_name,
        SUM(d.unit_cost * d.quantity) AS metric
    FROM products AS p
    JOIN deliveries AS d ON d.product_id = p.product_id
    GROUP BY p.product_id, p.name
    ORDER BY metric DESC, p.product_id
    LIMIT 1
) AS cost_leader;
