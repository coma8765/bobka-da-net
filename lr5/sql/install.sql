\set ON_ERROR_STOP on

\ir 00_schema.sql
\ir 01_build_documents.sql

SELECT
    (SELECT count(*) FROM lr5.delivery_documents)
        = (SELECT count(*) FROM public.deliveries)
    AND NOT EXISTS (
        SELECT 1
        FROM lr5.delivery_documents
        WHERE jsonb_typeof(document) <> 'object'
    ) AS lr5_install_valid \gset

\if :lr5_install_valid
    \echo 'LR5 objects installed successfully'
\else
    \echo 'LR5 object verification failed'
    \quit 4
\endif
