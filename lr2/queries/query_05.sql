-- Поставщики, совершавшие хотя бы одну поставку
SELECT s.supplier_id, s.name, s.city
FROM suppliers AS s
WHERE EXISTS (
    SELECT 1
    FROM deliveries AS d
    WHERE d.supplier_id = s.supplier_id
)
ORDER BY s.supplier_id;
