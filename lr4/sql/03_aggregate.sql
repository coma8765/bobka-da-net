\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION lr4.weighted_avg_unit_cost_sfunc(
    state numeric[],
    unit_cost numeric,
    quantity integer
)
RETURNS numeric[]
LANGUAGE plpython3u
IMMUTABLE
AS $python$
from decimal import Decimal

current_state = state
if current_state is None:
    current_state = [Decimal("0"), Decimal("0")]

if unit_cost is None or quantity is None:
    return current_state
if quantity <= 0:
    plpy.error("aggregate quantity must be greater than zero")
if unit_cost <= 0:
    plpy.error("aggregate unit cost must be greater than zero")

return [
    current_state[0] + Decimal(unit_cost) * Decimal(quantity),
    current_state[1] + Decimal(quantity),
]
$python$;

CREATE OR REPLACE FUNCTION lr4.weighted_avg_unit_cost_final(state numeric[])
RETURNS numeric
LANGUAGE plpython3u
IMMUTABLE
AS $python$
if state is None or state[1] == 0:
    return None
return state[0] / state[1]
$python$;

DROP AGGREGATE IF EXISTS lr4.weighted_avg_unit_cost(numeric, integer);

CREATE AGGREGATE lr4.weighted_avg_unit_cost(numeric, integer) (
    SFUNC = lr4.weighted_avg_unit_cost_sfunc,
    STYPE = numeric[],
    FINALFUNC = lr4.weighted_avg_unit_cost_final,
    INITCOND = '{0,0}',
    PARALLEL = UNSAFE
);
