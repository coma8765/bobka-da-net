-- Продажи и выручка по товарам
SELECT
    product_id,
    SUM(quantity) AS total_quantity,
    ROUND(SUM(unit_cost * quantity), 2) AS total_cost
INTO TEMPORARY TABLE best_selling
FROM deliveries
GROUP BY product_id;

SELECT product_id, total_quantity, total_cost
FROM best_selling
ORDER BY total_quantity DESC, product_id
LIMIT 10;
