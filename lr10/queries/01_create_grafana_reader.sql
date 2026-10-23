\set ON_ERROR_STOP on
\getenv grafana_password GRAFANA_DB_PASSWORD
\if :{?grafana_password}
\else
    \echo 'Set GRAFANA_DB_PASSWORD before running this script.'
    \quit 1
\endif

BEGIN;

SELECT 'CREATE ROLE grafana_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader')
\gexec

ALTER ROLE grafana_reader PASSWORD :'grafana_password';
ALTER ROLE grafana_reader SET timezone = 'UTC';
ALTER ROLE grafana_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE supply_lab TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON public.deliveries, public.suppliers, public.products, public.warehouses TO grafana_reader;

COMMIT;
