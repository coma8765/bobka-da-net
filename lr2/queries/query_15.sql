-- Категории дороже общей средней цены
SELECT category, ROUND(AVG(unit_price), 2) AS average_price
FROM products
GROUP BY category
HAVING AVG(unit_price) > (
    SELECT AVG(unit_price)
    FROM products
)
ORDER BY average_price DESC, category;
