\set ON_ERROR_STOP on

INSERT INTO lr5.delivery_documents (delivery_id, document)
SELECT
    d.delivery_id,
    jsonb_build_object(
        'delivery_id', d.delivery_id,
        'delivered_at', d.delivered_at,
        'supplier', jsonb_build_object(
            'id', s.supplier_id,
            'tax_id', s.tax_id,
            'name', s.name
        ),
        'product', jsonb_build_object(
            'id', p.product_id,
            'sku', p.sku,
            'name', p.name
        ),
        'warehouse', jsonb_build_object(
            'id', w.warehouse_id,
            'code', w.code,
            'name', w.name
        ),
        'batch', jsonb_build_object(
            'number', d.batch_number,
            'quantity', d.quantity,
            'unit_cost', d.unit_cost,
            'total_cost', d.quantity * d.unit_cost
        ),
        'quality', jsonb_build_object(
            'status', d.quality_status,
            'checks', jsonb_build_array(
                'documents',
                'quantity',
                'packaging'
            )
        ),
        'expires_on', d.expires_on
    )
FROM public.deliveries AS d
JOIN public.suppliers AS s USING (supplier_id)
JOIN public.products AS p USING (product_id)
JOIN public.warehouses AS w USING (warehouse_id)
ON CONFLICT (delivery_id) DO UPDATE
SET document = EXCLUDED.document,
    updated_at = clock_timestamp();

DELETE FROM lr5.delivery_documents AS doc
WHERE NOT EXISTS (
    SELECT 1
    FROM public.deliveries AS d
    WHERE d.delivery_id = doc.delivery_id
);
