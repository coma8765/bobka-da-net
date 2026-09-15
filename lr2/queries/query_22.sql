-- Среднее число поставок поставщика
WITH supplier_delivery_counts AS (
    SELECT s.supplier_id, COUNT(d.delivery_id) AS delivery_count
    FROM suppliers AS s
    LEFT JOIN deliveries AS d ON d.supplier_id = s.supplier_id
    GROUP BY s.supplier_id
)
SELECT ROUND(AVG(delivery_count), 2) AS average_deliveries
FROM supplier_delivery_counts;
