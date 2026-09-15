\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION lr4.delivery_total(
    p_quantity integer,
    p_unit_cost numeric
)
RETURNS numeric
LANGUAGE plpython3u
IMMUTABLE
STRICT
AS $python$
from decimal import Decimal, ROUND_HALF_UP

if p_quantity <= 0:
    plpy.error("quantity must be greater than zero")
if p_unit_cost <= 0:
    plpy.error("unit cost must be greater than zero")

total = Decimal(p_quantity) * Decimal(p_unit_cost)
return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
$python$;

