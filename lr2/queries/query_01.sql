-- Активные поставщики России с высоким рейтингом
SELECT supplier_id, name, city, rating
FROM suppliers
WHERE country = 'Russia'
  AND is_active = true
  AND rating >= 4.00
ORDER BY rating DESC, supplier_id;
