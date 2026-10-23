\set ON_ERROR_STOP on
-- Usage: psql ... -v file_id=UUID -v expected_count=N -f tests/verify_database.sql
SELECT set_config('lr8.test_file_id', :'file_id', false);
SELECT set_config('lr8.test_expected_count', :'expected_count', false);
DO $$
DECLARE
    actual integer;
    expected integer := current_setting('lr8.test_expected_count')::integer;
    source uuid := current_setting('lr8.test_file_id')::uuid;
BEGIN
    SELECT count(*) INTO actual FROM lr8.delivery_events WHERE source_file_id = source;
    IF actual <> expected THEN
        RAISE EXCEPTION 'Expected % records for %, got %', expected, source, actual;
    END IF;
    IF EXISTS (
        SELECT 1 FROM lr8.delivery_events
        WHERE source_file_id = source
          AND (quantity <= 0 OR unit_cost <= 0 OR loaded_at IS NULL
               OR quality_status NOT IN ('accepted', 'inspection', 'rejected'))
    ) THEN
        RAISE EXCEPTION 'Invalid loaded values';
    END IF;
    IF EXISTS (SELECT event_id FROM lr8.delivery_events GROUP BY event_id HAVING count(*) > 1)
       OR EXISTS (SELECT batch_number FROM lr8.delivery_events GROUP BY batch_number HAVING count(*) > 1)
    THEN
        RAISE EXCEPTION 'Duplicate business or event keys';
    END IF;
END $$;
SELECT source_file_id, count(*) AS records, min(loaded_at) AS loaded_at
FROM lr8.delivery_events WHERE source_file_id = :'file_id'::uuid
GROUP BY source_file_id;
