\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION lr4.is_positive_quantity(p_value integer)
RETURNS boolean
LANGUAGE plpython3u
IMMUTABLE
AS $python$
if p_value is None:
    return True
return p_value > 0
$python$;

SELECT to_regtype('lr4.positive_quantity') IS NULL
    AS positive_quantity_missing \gset

\if :positive_quantity_missing
    CREATE DOMAIN lr4.positive_quantity AS integer
        CONSTRAINT positive_quantity_check
        CHECK (lr4.is_positive_quantity(VALUE));
\endif

SELECT EXISTS (
    SELECT 1
    FROM pg_type AS t
    JOIN pg_namespace AS n ON n.oid = t.typnamespace
    WHERE n.nspname = 'lr4'
      AND t.typname = 'positive_quantity'
      AND t.typtype = 'd'
      AND t.typbasetype = 'integer'::regtype
) AS positive_quantity_valid \gset

\if :positive_quantity_valid
\else
    \echo 'lr4.positive_quantity exists but is not the expected integer domain'
    \quit 4
\endif

