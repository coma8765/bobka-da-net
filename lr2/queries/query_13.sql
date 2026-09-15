-- Самый поставляемый товар по количеству
SELECT p.product_id, p.name
FROM products AS p
WHERE p.product_id = (
    SELECT ranked.product_id
    FROM (
        SELECT d.product_id, SUM(d.quantity) AS total_quantity
        FROM deliveries AS d
        GROUP BY d.product_id
    ) AS ranked
    WHERE ranked.total_quantity = (
        SELECT MAX(totals.total_quantity)
        FROM (
            SELECT SUM(d2.quantity) AS total_quantity
            FROM deliveries AS d2
            GROUP BY d2.product_id
        ) AS totals
    )
    ORDER BY ranked.product_id
    LIMIT 1
);
