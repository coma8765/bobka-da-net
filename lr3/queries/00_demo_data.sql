\set ON_ERROR_STOP on
\connect supply_lab

-- Данные для демонстрации ежедневной статистики. Повторный запуск переносит
-- те же поставки на вчерашнюю дату и не создаёт дубликаты бизнес-ключей.
WITH selected_supplier AS (
    SELECT s.supplier_id
    FROM public.suppliers AS s
    ORDER BY s.supplier_id
    LIMIT 1
),
selected_product AS (
    SELECT p.product_id
    FROM public.products AS p
    WHERE NOT p.is_perishable
    ORDER BY p.product_id
    LIMIT 1
),
selected_warehouses AS (
    SELECT
        w.warehouse_id,
        row_number() OVER (ORDER BY w.warehouse_id)::integer
            AS warehouse_position
    FROM public.warehouses AS w
    ORDER BY w.warehouse_id
    LIMIT 3
),
demo_deliveries(warehouse_position, sequence_number, quantity) AS (
    VALUES
        (1, 1, 12),
        (1, 2, 8),
        (1, 3, 10),
        (2, 1, 20),
        (2, 2, 15),
        (3, 1, 25)
)
INSERT INTO public.deliveries (
    supplier_id,
    product_id,
    warehouse_id,
    delivered_at,
    quantity,
    unit_cost,
    batch_number,
    quality_status,
    expires_on
)
SELECT
    supplier.supplier_id,
    product.product_id,
    warehouse.warehouse_id,
    (current_date - 1)::timestamp
        + interval '12 hours'
        + make_interval(
            secs => demo.warehouse_position * 100 + demo.sequence_number
        ),
    demo.quantity,
    (100 + demo.warehouse_position)::numeric(12, 2),
    format(
        'LR3-STAT-D%s-%s',
        demo.warehouse_position,
        demo.sequence_number
    ),
    'accepted',
    NULL
FROM demo_deliveries AS demo
JOIN selected_warehouses AS warehouse
  ON warehouse.warehouse_position = demo.warehouse_position
CROSS JOIN selected_supplier AS supplier
CROSS JOIN selected_product AS product
ON CONFLICT ON CONSTRAINT deliveries_business_key_uq DO UPDATE
SET delivered_at = EXCLUDED.delivered_at,
    quantity = EXCLUDED.quantity,
    unit_cost = EXCLUDED.unit_cost,
    quality_status = EXCLUDED.quality_status,
    expires_on = EXCLUDED.expires_on;

