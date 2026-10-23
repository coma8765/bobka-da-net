\set ON_ERROR_STOP on
BEGIN;
-- Every mutation in this test is rolled back.
DO $$
DECLARE
    first_id uuid := gen_random_uuid();
    source uuid := gen_random_uuid();
    batch text := 'TEST-' || replace(gen_random_uuid()::text, '-', '');
    original_count bigint;
BEGIN
    SELECT count(*) INTO original_count FROM lr8.delivery_events;
    INSERT INTO lr8.delivery_events VALUES
        (first_id, source, '7700000001', 'SKU-000001', 'WH-00001', now(),
         10, 12.50, batch, 'accepted', NULL, DEFAULT);
    BEGIN
        INSERT INTO lr8.delivery_events SELECT * FROM lr8.delivery_events WHERE event_id = first_id;
        RAISE EXCEPTION 'duplicate accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO lr8.delivery_events VALUES
            (gen_random_uuid(), source, '7700000001', 'SKU-000001', 'WH-00001', now(),
             1, 12.50, batch || '-a', 'accepted', NULL, DEFAULT),
            (gen_random_uuid(), source, '7700000001', 'SKU-000001', 'WH-00001', now(),
             0, 12.50, batch || '-b', 'accepted', NULL, DEFAULT);
        RAISE EXCEPTION 'invalid quantity accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    IF (SELECT count(*) FROM lr8.delivery_events) <> original_count + 1 THEN
        RAISE EXCEPTION 'partial INSERT was committed';
    END IF;
    BEGIN
        INSERT INTO lr8.delivery_events VALUES
            (gen_random_uuid(), source, '', 'SKU-000001', 'WH-00001', now(),
             1, 12.50, batch || '-c', 'accepted', NULL, DEFAULT);
        RAISE EXCEPTION 'empty natural key accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;
ROLLBACK;
