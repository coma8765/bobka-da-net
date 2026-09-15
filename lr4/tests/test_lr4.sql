\set ON_ERROR_STOP on

BEGIN;

INSERT INTO public.suppliers (
    name,
    tax_id,
    country,
    city,
    email,
    phone,
    rating,
    is_active,
    created_at
)
VALUES (
    'LR4 Test Supplier',
    'LR4T00000001',
    'Russia',
    'Moscow',
    'lr4-test-supplier@example.test',
    '+70000000001',
    4.50,
    true,
    date '2026-01-01'
)
RETURNING supplier_id AS test_supplier_id \gset

INSERT INTO public.products (
    sku,
    name,
    category,
    unit,
    unit_price,
    weight_kg,
    is_perishable,
    created_at
)
VALUES (
    'LR4-TEST-SKU',
    'LR4 Test Product',
    'test',
    'pcs',
    25.00,
    1.000,
    false,
    date '2026-01-01'
)
RETURNING product_id AS test_product_id \gset

INSERT INTO public.warehouses (
    code,
    name,
    country,
    city,
    address,
    opened_on
)
VALUES (
    'LR4-TEST-WH',
    'LR4 Test Warehouse',
    'Russia',
    'Moscow',
    'LR4 test address',
    date '2026-01-01'
)
RETURNING warehouse_id AS test_warehouse_id \gset

CALL lr4.register_delivery(
    :test_supplier_id,
    :test_product_id,
    :test_warehouse_id,
    timestamp '2026-01-10 12:00:00',
    2::lr4.positive_quantity,
    10.00,
    'LR4-TEST-001',
    'accepted',
    NULL
);

SELECT delivery_id AS first_delivery_id
FROM public.deliveries
WHERE supplier_id = :test_supplier_id
  AND product_id = :test_product_id
  AND warehouse_id = :test_warehouse_id
  AND batch_number = 'LR4-TEST-001' \gset

CALL lr4.register_delivery(
    :test_supplier_id,
    :test_product_id,
    :test_warehouse_id,
    timestamp '2026-01-11 12:00:00',
    3::lr4.positive_quantity,
    20.00,
    'LR4-TEST-002',
    'inspection',
    NULL
);

DO LANGUAGE plpython3u $python$
from decimal import Decimal

result = plpy.execute(
    """
    SELECT
        lr4.delivery_total(12, 125.50) AS total,
        lr4.delivery_total(NULL, 125.50) AS null_total
    """
)[0]

if result["total"] != Decimal("1506.00"):
    plpy.error("scalar function returned an unexpected total")
if result["null_total"] is not None:
    plpy.error("strict scalar function did not return NULL")

try:
    plpy.execute("SELECT lr4.delivery_total(0, 10.00)")
except plpy.SPIError:
    pass
else:
    plpy.error("scalar function accepted zero quantity")
$python$;

DO LANGUAGE plpython3u $python$
from decimal import Decimal

result = plpy.execute(
    """
    SELECT lr4.weighted_avg_unit_cost(unit_cost, quantity) AS actual
    FROM public.deliveries
    WHERE batch_number IN ('LR4-TEST-001', 'LR4-TEST-002')
    """
)[0]

if result["actual"] != Decimal("16.00"):
    plpy.error("aggregate returned an unexpected weighted average")

empty_result = plpy.execute(
    """
    SELECT lr4.weighted_avg_unit_cost(unit_cost, quantity) AS actual
    FROM (
        SELECT NULL::numeric AS unit_cost, NULL::integer AS quantity
        WHERE false
    ) AS empty_input
    """
)[0]

if empty_result["actual"] is not None:
    plpy.error("aggregate over an empty set did not return NULL")

try:
    plpy.execute(
        """
        SELECT lr4.weighted_avg_unit_cost(unit_cost, quantity)
        FROM (VALUES (10.00::numeric, -1::integer)) AS input(unit_cost, quantity)
        """
    )
except plpy.SPIError:
    pass
else:
    plpy.error("aggregate accepted a negative quantity")
$python$;

DO LANGUAGE plpython3u $python$
valid = plpy.execute(
    "SELECT (5::lr4.positive_quantity)::integer AS actual"
)[0]
if valid["actual"] != 5:
    plpy.error("positive quantity domain changed a valid value")

for invalid_value in (0, -1):
    try:
        plan = plpy.prepare(
            "SELECT $1::lr4.positive_quantity",
            ["integer"],
        )
        plpy.execute(plan, [invalid_value])
    except plpy.SPIError:
        pass
    else:
        plpy.error("positive quantity domain accepted %s" % invalid_value)
$python$;

CALL lr4.register_delivery(
    :test_supplier_id,
    :test_product_id,
    :test_warehouse_id,
    timestamp '2026-02-01 00:00:00',
    7::lr4.positive_quantity,
    30.00,
    'LR4-TEST-BOUNDARY',
    'accepted',
    NULL
);

DO LANGUAGE plpython3u $python$
from decimal import Decimal

result = plpy.execute(
    """
    SELECT summary.*
    FROM lr4.supplier_delivery_summary(
        timestamp '2026-01-01 00:00:00',
        timestamp '2026-02-01 00:00:00'
    ) AS summary
    JOIN public.suppliers AS supplier USING (supplier_id)
    WHERE supplier.tax_id = 'LR4T00000001'
    """
)

if len(result) != 1:
    plpy.error("table function did not return exactly one test supplier")

summary = result[0]
if summary["deliveries_count"] != 2:
    plpy.error("table function included a delivery on the right boundary")
if summary["total_quantity"] != 5:
    plpy.error("table function returned an unexpected total quantity")
if summary["total_cost"] != Decimal("80.00"):
    plpy.error("table function returned an unexpected total cost")

for start_value, end_value in (
    ("2026-01-01 00:00:00", "2026-01-01 00:00:00"),
    ("2026-02-01 00:00:00", "2026-01-01 00:00:00"),
):
    plan = plpy.prepare(
        "SELECT * FROM lr4.supplier_delivery_summary($1, $2)",
        ["timestamp", "timestamp"],
    )
    try:
        plpy.execute(plan, [start_value, end_value])
    except plpy.SPIError:
        pass
    else:
        plpy.error("table function accepted an invalid interval")
$python$;

DO LANGUAGE plpython3u $python$
ids = plpy.execute(
    """
    SELECT
        s.supplier_id,
        p.product_id,
        w.warehouse_id
    FROM public.suppliers AS s
    CROSS JOIN public.products AS p
    CROSS JOIN public.warehouses AS w
    WHERE s.tax_id = 'LR4T00000001'
      AND p.sku = 'LR4-TEST-SKU'
      AND w.code = 'LR4-TEST-WH'
    """
)[0]

call_plan = plpy.prepare(
    """
    CALL lr4.register_delivery($1, $2, $3, $4, $5, $6, $7, $8, $9)
    """,
    [
        "bigint",
        "bigint",
        "bigint",
        "timestamp",
        "lr4.positive_quantity",
        "numeric",
        "varchar",
        "varchar",
        "date",
    ],
)

cases = [
    [
        -1,
        ids["product_id"],
        ids["warehouse_id"],
        "2026-01-12 12:00:00",
        1,
        10,
        "LR4-TEST-BAD-FK",
        "accepted",
        None,
    ],
    [
        ids["supplier_id"],
        ids["product_id"],
        ids["warehouse_id"],
        "2026-01-10 12:00:00",
        2,
        10,
        "LR4-TEST-001",
        "accepted",
        None,
    ],
    [
        ids["supplier_id"],
        ids["product_id"],
        ids["warehouse_id"],
        "2026-01-12 12:00:00",
        1,
        10,
        "LR4-TEST-BAD-STATUS",
        "unknown",
        None,
    ],
]

for case in cases:
    try:
        plpy.execute(call_plan, case)
    except plpy.SPIError:
        pass
    else:
        plpy.error("register_delivery accepted an invalid call")
$python$;

UPDATE public.deliveries
SET quantity = 4
WHERE delivery_id = :first_delivery_id;

DELETE FROM public.deliveries
WHERE delivery_id = :first_delivery_id;

DO LANGUAGE plpython3u $python$
rows = plpy.execute(
    """
    SELECT
        operation,
        old_row IS NULL AS old_is_null,
        new_row IS NULL AS new_is_null,
        (old_row->>'quantity')::integer AS old_quantity,
        (new_row->>'quantity')::integer AS new_quantity
    FROM lr4.delivery_audit
    WHERE delivery_id = (
        SELECT delivery_id
        FROM lr4.delivery_audit
        WHERE coalesce(
            new_row->>'batch_number',
            old_row->>'batch_number'
        ) = 'LR4-TEST-001'
        ORDER BY audit_id
        LIMIT 1
    )
    ORDER BY audit_id
    """
)

if [row["operation"] for row in rows] != ["INSERT", "UPDATE", "DELETE"]:
    plpy.error("audit trigger did not record INSERT, UPDATE, DELETE in order")
if not rows[0]["old_is_null"] or rows[0]["new_quantity"] != 2:
    plpy.error("INSERT audit snapshot is invalid")
if rows[1]["old_quantity"] != 2 or rows[1]["new_quantity"] != 4:
    plpy.error("UPDATE audit snapshots are invalid")
if rows[2]["old_quantity"] != 4 or not rows[2]["new_is_null"]:
    plpy.error("DELETE audit snapshot is invalid")
$python$;

SAVEPOINT audit_rollback_test;

CALL lr4.register_delivery(
    :test_supplier_id,
    :test_product_id,
    :test_warehouse_id,
    timestamp '2026-01-15 12:00:00',
    1::lr4.positive_quantity,
    10.00,
    'LR4-TEST-ROLLBACK',
    'accepted',
    NULL
);

ROLLBACK TO SAVEPOINT audit_rollback_test;
RELEASE SAVEPOINT audit_rollback_test;

DO LANGUAGE plpython3u $python$
delivery_count = plpy.execute(
    """
    SELECT count(*) AS count
    FROM public.deliveries
    WHERE batch_number = 'LR4-TEST-ROLLBACK'
    """
)[0]["count"]

audit_count = plpy.execute(
    """
    SELECT count(*) AS count
    FROM lr4.delivery_audit
    WHERE new_row->>'batch_number' = 'LR4-TEST-ROLLBACK'
    """
)[0]["count"]

if delivery_count != 0 or audit_count != 0:
    plpy.error("savepoint rollback left a delivery or its audit record")
$python$;

DO LANGUAGE plpython3u $python$
objects = plpy.execute(
    """
    SELECT
        count(*) FILTER (
            WHERE p.proname = 'delivery_total' AND p.prokind = 'f'
        ) AS scalar_count,
        count(*) FILTER (
            WHERE p.proname = 'weighted_avg_unit_cost' AND p.prokind = 'a'
        ) AS aggregate_count,
        count(*) FILTER (
            WHERE p.proname = 'supplier_delivery_summary' AND p.prokind = 'f'
        ) AS table_function_count,
        count(*) FILTER (
            WHERE p.proname = 'register_delivery' AND p.prokind = 'p'
        ) AS procedure_count,
        bool_and(l.lanname = 'plpython3u') FILTER (
            WHERE p.prokind IN ('f', 'p')
        ) AS python_only
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    JOIN pg_language AS l ON l.oid = p.prolang
    WHERE n.nspname = 'lr4'
    """
)[0]

if objects["scalar_count"] != 1:
    plpy.error("scalar function is missing")
if objects["aggregate_count"] != 1:
    plpy.error("aggregate is missing")
if objects["table_function_count"] != 1:
    plpy.error("table function is missing")
if objects["procedure_count"] != 1:
    plpy.error("procedure is missing")
if not objects["python_only"]:
    plpy.error("a procedural LR4 object uses a language other than PL/Python")

domain = plpy.execute(
    """
    SELECT t.typtype
    FROM pg_type AS t
    JOIN pg_namespace AS n ON n.oid = t.typnamespace
    WHERE n.nspname = 'lr4' AND t.typname = 'positive_quantity'
    """
)
if len(domain) != 1 or domain[0]["typtype"] != "d":
    plpy.error("positive_quantity is not a domain")

trigger = plpy.execute(
    """
    SELECT tgenabled
    FROM pg_trigger
    WHERE tgrelid = 'public.deliveries'::regclass
      AND tgname = 'deliveries_audit_trg'
      AND NOT tgisinternal
    """
)
if len(trigger) != 1 or trigger[0]["tgenabled"] != "O":
    plpy.error("delivery audit trigger is missing or disabled")
$python$;

ROLLBACK;

\echo 'All LR4 tests passed'
