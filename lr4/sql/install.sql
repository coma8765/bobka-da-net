\set ON_ERROR_STOP on

\ir 00_preflight.sql
\ir 01_schema_and_type.sql
\ir 02_scalar_function.sql
\ir 03_aggregate.sql
\ir 04_table_function.sql
\ir 05_procedure.sql
\ir 06_trigger.sql

SELECT
    EXISTS (
        SELECT 1
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'lr4'
          AND p.proname = 'delivery_total'
          AND p.prokind = 'f'
    )
    AND EXISTS (
        SELECT 1
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'lr4'
          AND p.proname = 'weighted_avg_unit_cost'
          AND p.prokind = 'a'
    )
    AND EXISTS (
        SELECT 1
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'lr4'
          AND p.proname = 'supplier_delivery_summary'
          AND p.prokind = 'f'
    )
    AND EXISTS (
        SELECT 1
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'lr4'
          AND p.proname = 'register_delivery'
          AND p.prokind = 'p'
    )
    AND EXISTS (
        SELECT 1
        FROM pg_type AS t
        JOIN pg_namespace AS n ON n.oid = t.typnamespace
        WHERE n.nspname = 'lr4'
          AND t.typname = 'positive_quantity'
          AND t.typtype = 'd'
    )
    AND EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'public.deliveries'::regclass
          AND tgname = 'deliveries_audit_trg'
          AND NOT tgisinternal
    ) AS lr4_install_valid \gset

\if :lr4_install_valid
    \echo 'LR4 objects installed successfully'
\else
    \echo 'LR4 object verification failed'
    \quit 4
\endif

