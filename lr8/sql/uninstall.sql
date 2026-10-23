\set ON_ERROR_STOP on
-- Explicitly removes only the laboratory table, including its data.
BEGIN;
DROP TABLE IF EXISTS lr8.delivery_events;
DROP SCHEMA IF EXISTS lr8;
COMMIT;
