\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION lr4.supplier_delivery_summary(
    p_from timestamp without time zone,
    p_to timestamp without time zone
)
RETURNS TABLE (
    supplier_id bigint,
    supplier_name varchar,
    deliveries_count bigint,
    total_quantity bigint,
    total_cost numeric
)
LANGUAGE plpython3u
STABLE
AS $python$
if p_from is None or p_to is None:
    plpy.error("both interval boundaries are required")
if p_from >= p_to:
    plpy.error("the interval start must be earlier than its end")

plan_key = "supplier_delivery_summary_plan"
if plan_key not in SD:
    SD[plan_key] = plpy.prepare(
        """
        SELECT
            s.supplier_id,
            s.name AS supplier_name,
            count(d.delivery_id) AS deliveries_count,
            coalesce(sum(d.quantity), 0)::bigint AS total_quantity,
            coalesce(sum(d.quantity * d.unit_cost), 0) AS total_cost
        FROM public.suppliers AS s
        JOIN public.deliveries AS d ON d.supplier_id = s.supplier_id
        WHERE d.delivered_at >= $1 AND d.delivered_at < $2
        GROUP BY s.supplier_id, s.name
        ORDER BY total_cost DESC, s.supplier_id
        """,
        ["timestamp", "timestamp"],
    )

rows = plpy.execute(SD[plan_key], [p_from, p_to])
return [dict(row) for row in rows]
$python$;

