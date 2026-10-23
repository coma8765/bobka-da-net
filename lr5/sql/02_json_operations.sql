\set ON_ERROR_STOP on

-- 1. Extract a nested JSON fragment without converting it to text.
SELECT delivery_id, document -> 'product' AS product
FROM lr5.delivery_documents
ORDER BY delivery_id;

-- 2. Extract the value of a concrete nested node as text.
SELECT delivery_id, document #>> '{supplier,name}' AS supplier_name
FROM lr5.delivery_documents
ORDER BY delivery_id;

-- 3. Check the existence of a top-level key and nested array elements.
SELECT
    delivery_id,
    document ? 'expires_on' AS has_expiration_key,
    document @? '$.quality.checks[*]' AS has_quality_checks
FROM lr5.delivery_documents
ORDER BY delivery_id;

-- 4. Add a nested value while preserving the rest of the document.
-- The transaction is rolled back so that this demonstration is repeatable.
BEGIN;

UPDATE lr5.delivery_documents
SET document = jsonb_set(
        document,
        '{quality,reviewed_by}',
        to_jsonb('lr5-demo'::text),
        true
    ),
    updated_at = clock_timestamp()
WHERE delivery_id = (
    SELECT min(delivery_id)
    FROM lr5.delivery_documents
);

SELECT
    delivery_id,
    document #>> '{quality,reviewed_by}' AS reviewed_by
FROM lr5.delivery_documents
WHERE delivery_id = (
    SELECT min(delivery_id)
    FROM lr5.delivery_documents
);

ROLLBACK;

-- 5. Split every checks array into separate relational rows.
SELECT d.delivery_id, c.check_name
FROM lr5.delivery_documents AS d
CROSS JOIN LATERAL jsonb_array_elements_text(
    d.document #> '{quality,checks}'
) AS c(check_name)
ORDER BY d.delivery_id, c.check_name;

-- ф-ция возвращающая jsonb

CREATE OR REPLACE FUNCTION public.fn_delivery_total_via_jsonb(p_delivery_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
STRICT
AS $$
DECLARE
BEGIN
    RETURN SELECT
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
    WHERE delivery_id = p_delivery_id
    SET document = EXCLUDED.document,
        updated_at = clock_timestamp()
END;
$$;

