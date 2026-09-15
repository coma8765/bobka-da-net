-- Поставки за лето 2025 года
SELECT delivery_id, supplier_id, product_id, delivered_at
FROM deliveries
WHERE delivered_at::date BETWEEN DATE '2025-06-01' AND DATE '2025-08-31'
ORDER BY delivered_at, delivery_id;
