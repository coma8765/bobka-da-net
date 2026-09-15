-- 2 даты и по ним найти склад который чаще заполнялся
\set date_from '2025-01-01'
\set date_to '2025-12-31'

SELECT
    w.warehouse_id,
    w.code,
    w.name,
    w.city,
    COUNT(*) AS delivery_count
FROM warehouses AS w
JOIN deliveries AS d ON d.warehouse_id = w.warehouse_id
WHERE d.delivered_at >= :'date_from'::date
  AND d.delivered_at < :'date_to'::date + INTERVAL '1 day'
GROUP BY w.warehouse_id, w.code, w.name, w.city
ORDER BY delivery_count DESC, w.warehouse_id
LIMIT 1;
