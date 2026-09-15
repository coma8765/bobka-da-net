-- Товары дороже всех продуктов категории Food
SELECT product_id, name, category, unit_price
FROM products
WHERE unit_price > ALL (
    SELECT unit_price
    FROM products
    WHERE category = 'Food'
)
ORDER BY unit_price DESC, product_id;
