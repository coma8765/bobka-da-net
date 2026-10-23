SELECT
    p.product_id,
    p.sku,
    p.name,
    COUNT(*) AS delivery_count,
    SUM(d.quantity * d.unit_cost) AS total_cost
FROM public.deliveries AS d
JOIN public.products AS p ON p.product_id = d.product_id
WHERE d.quality_status = 'accepted'
GROUP BY p.product_id, p.sku, p.name
ORDER BY total_cost DESC, p.product_id ASC
LIMIT 10;

