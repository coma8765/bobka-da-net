\set ON_ERROR_STOP on

CREATE OR REPLACE PROCEDURE lr4.register_delivery(
    p_supplier_id bigint,
    p_product_id bigint,
    p_warehouse_id bigint,
    p_delivered_at timestamp without time zone,
    p_quantity lr4.positive_quantity,
    p_unit_cost numeric,
    p_batch_number varchar,
    p_quality_status varchar,
    p_expires_on date DEFAULT NULL
)
LANGUAGE plpython3u
SECURITY INVOKER
AS $python$
from plpy import spiexceptions

if p_quantity is None:
    plpy.error("quantity is required")
if p_unit_cost is None or p_unit_cost <= 0:
    plpy.error("unit cost must be greater than zero")
if p_delivered_at is None:
    plpy.error("delivery timestamp is required")
if p_batch_number is None or not p_batch_number.strip():
    plpy.error("batch number is required")
if p_quality_status not in ("accepted", "inspection", "rejected"):
    plpy.error("quality status must be accepted, inspection, or rejected")

plan_key = "register_delivery_plan"
if plan_key not in SD:
    SD[plan_key] = plpy.prepare(
        """
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
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING delivery_id
        """,
        [
            "bigint",
            "bigint",
            "bigint",
            "timestamp",
            "integer",
            "numeric",
            "varchar",
            "varchar",
            "date",
        ],
    )

try:
    result = plpy.execute(
        SD[plan_key],
        [
            p_supplier_id,
            p_product_id,
            p_warehouse_id,
            p_delivered_at,
            p_quantity,
            p_unit_cost,
            p_batch_number,
            p_quality_status,
            p_expires_on,
        ],
    )
except spiexceptions.ForeignKeyViolation:
    plpy.error("supplier, product, or warehouse does not exist")
except spiexceptions.UniqueViolation:
    plpy.error("a delivery with the same business key already exists")
except spiexceptions.CheckViolation as error:
    plpy.error("delivery violates a data constraint: %s" % error)

plpy.notice("registered delivery_id=%s" % result[0]["delivery_id"])
$python$;

