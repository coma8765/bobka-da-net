-- Принятые поставки на московские склады
SELECT delivery_id, supplier_id, product_id, warehouse_id, delivered_at
FROM deliveries
WHERE warehouse_id IN (
    SELECT warehouse_id
    FROM warehouses
    WHERE city = 'Moscow'
)
  AND quality_status = 'accepted'
ORDER BY delivered_at, delivery_id;
