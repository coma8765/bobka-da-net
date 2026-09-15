\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS lr4.delivery_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation varchar(6) NOT NULL
        CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    delivery_id bigint NOT NULL,
    changed_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    changed_by text NOT NULL DEFAULT session_user,
    old_row jsonb,
    new_row jsonb
);

CREATE OR REPLACE FUNCTION lr4.audit_delivery()
RETURNS trigger
LANGUAGE plpython3u
VOLATILE
AS $python$
import json

event = TD["event"]
old_row = TD.get("old")
new_row = TD.get("new")
source_row = new_row if new_row is not None else old_row

if source_row is None:
    plpy.error("row-level delivery trigger received no row")

def encode_row(row):
    if row is None:
        return None
    return json.dumps(dict(row), default=str, ensure_ascii=False, sort_keys=True)

plan_key = "audit_delivery_plan"
if plan_key not in SD:
    SD[plan_key] = plpy.prepare(
        """
        INSERT INTO lr4.delivery_audit (
            operation,
            delivery_id,
            old_row,
            new_row
        )
        VALUES (
            $1,
            $2,
            CASE WHEN $3 IS NULL THEN NULL ELSE $3::jsonb END,
            CASE WHEN $4 IS NULL THEN NULL ELSE $4::jsonb END
        )
        """,
        ["text", "bigint", "text", "text"],
    )

plpy.execute(
    SD[plan_key],
    [
        event,
        source_row["delivery_id"],
        encode_row(old_row),
        encode_row(new_row),
    ],
)

return None
$python$;

DROP TRIGGER IF EXISTS deliveries_audit_trg ON public.deliveries;

CREATE TRIGGER deliveries_audit_trg
AFTER INSERT OR UPDATE OR DELETE ON public.deliveries
FOR EACH ROW
EXECUTE FUNCTION lr4.audit_delivery();

