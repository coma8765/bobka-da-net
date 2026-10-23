\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS lr7;

CREATE TABLE IF NOT EXISTS lr7.delivery_tags (
    tag_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_id bigint NOT NULL
        REFERENCES public.deliveries (delivery_id) ON DELETE CASCADE,
    tag varchar(40) NOT NULL CHECK (btrim(tag) <> ''),
    created_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT delivery_tags_uq UNIQUE (delivery_id, tag)
);

COMMIT;
