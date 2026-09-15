\set ON_ERROR_STOP on

BEGIN;
DROP TRIGGER IF EXISTS deliveries_audit_trg ON public.deliveries;
DROP SCHEMA IF EXISTS lr4 CASCADE;
COMMIT;

