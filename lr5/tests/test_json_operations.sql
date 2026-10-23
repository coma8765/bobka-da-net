\set ON_ERROR_STOP on

DO $document_checks$
BEGIN
    IF (SELECT count(*) FROM lr5.delivery_documents)
        <> (SELECT count(*) FROM public.deliveries) THEN
        RAISE EXCEPTION 'Not every delivery has a JSONB document';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM lr5.delivery_documents AS doc
        JOIN public.deliveries AS d USING (delivery_id)
        WHERE jsonb_typeof(doc.document) <> 'object'
           OR (doc.document ->> 'delivery_id')::bigint <> d.delivery_id
           OR (doc.document #>> '{supplier,id}')::bigint <> d.supplier_id
           OR (doc.document #>> '{product,id}')::bigint <> d.product_id
           OR (doc.document #>> '{warehouse,id}')::bigint <> d.warehouse_id
           OR (doc.document #>> '{batch,quantity}')::integer <> d.quantity
           OR (doc.document #>> '{batch,unit_cost}')::numeric <> d.unit_cost
           OR (doc.document #>> '{batch,total_cost}')::numeric
                <> d.quantity * d.unit_cost
    ) THEN
        RAISE EXCEPTION 'A delivery document contains inconsistent values';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM lr5.delivery_documents
        WHERE jsonb_typeof(document -> 'product') <> 'object'
    ) THEN
        RAISE EXCEPTION 'Product fragment is not a JSON object';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM lr5.delivery_documents AS doc
        JOIN public.deliveries AS d USING (delivery_id)
        JOIN public.suppliers AS s USING (supplier_id)
        WHERE doc.document #>> '{supplier,name}' IS DISTINCT FROM s.name
    ) THEN
        RAISE EXCEPTION 'Supplier name extraction returned a wrong value';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM lr5.delivery_documents
        WHERE NOT (document ? 'expires_on')
           OR NOT (document @? '$.quality.checks[*]')
           OR document @? '$.quality.missing_node'
    ) THEN
        RAISE EXCEPTION 'JSON node existence checks failed';
    END IF;

    IF (SELECT count(*)
        FROM lr5.delivery_documents AS doc
        CROSS JOIN LATERAL jsonb_array_elements_text(
            doc.document #> '{quality,checks}'
        ))
        <> (SELECT sum(jsonb_array_length(document #> '{quality,checks}'))
            FROM lr5.delivery_documents) THEN
        RAISE EXCEPTION 'Splitting checks arrays returned a wrong row count';
    END IF;
END
$document_checks$;

BEGIN;

CREATE TEMP TABLE document_before_update ON COMMIT DROP AS
SELECT delivery_id, document
FROM lr5.delivery_documents
ORDER BY delivery_id
LIMIT 1;

UPDATE lr5.delivery_documents AS doc
SET document = jsonb_set(
        doc.document,
        '{quality,reviewed_by}',
        to_jsonb('lr5-test'::text),
        true
    ),
    updated_at = clock_timestamp()
FROM document_before_update AS original
WHERE doc.delivery_id = original.delivery_id;

DO $update_check$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM lr5.delivery_documents AS doc
        JOIN document_before_update AS original USING (delivery_id)
        WHERE doc.document #>> '{quality,reviewed_by}' = 'lr5-test'
          AND doc.document #- '{quality,reviewed_by}' = original.document
    ) THEN
        RAISE EXCEPTION 'jsonb_set changed unexpected document fields';
    END IF;
END
$update_check$;

ROLLBACK;

SELECT 'LR5 JSONB operation tests passed' AS result;
