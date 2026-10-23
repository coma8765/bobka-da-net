\set ON_ERROR_STOP on
\connect supply_lab

BEGIN;

-- Проверка задания 1: скалярная функция.
DO $$
DECLARE
    v_delivery_id bigint;
    v_expected numeric(20, 2);
    v_actual numeric(20, 2);
BEGIN
    SELECT
        d.delivery_id,
        (d.quantity::numeric * d.unit_cost)::numeric(20, 2)
    INTO v_delivery_id, v_expected
    FROM public.deliveries AS d
    ORDER BY d.delivery_id
    LIMIT 1;

    v_actual := public.fn_delivery_total(v_delivery_id);

    IF v_actual IS DISTINCT FROM v_expected THEN
        RAISE EXCEPTION 'fn_delivery_total returned %, expected %',
            v_actual, v_expected;
    END IF;

    BEGIN
        PERFORM public.fn_delivery_total(-1);
        RAISE EXCEPTION 'fn_delivery_total accepted an unknown delivery';
    EXCEPTION
        WHEN SQLSTATE 'P0002' THEN
            NULL;
    END;
END;
$$;

-- Проверка задания 2: подставляемая табличная функция.
DO $$
DECLARE
    v_supplier_id bigint;
    v_expected_count bigint;
    v_actual_count bigint;
BEGIN
    SELECT d.supplier_id
    INTO v_supplier_id
    FROM public.deliveries AS d
    GROUP BY d.supplier_id
    ORDER BY count(*) DESC, d.supplier_id
    LIMIT 1;

    SELECT count(*)
    INTO v_expected_count
    FROM public.deliveries AS d
    WHERE d.supplier_id = v_supplier_id;

    SELECT count(*)
    INTO v_actual_count
    FROM public.fn_supplier_deliveries(v_supplier_id);

    IF v_actual_count <> v_expected_count THEN
        RAISE EXCEPTION 'fn_supplier_deliveries returned % rows, expected %',
            v_actual_count, v_expected_count;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.fn_supplier_deliveries(v_supplier_id) AS result
        JOIN public.deliveries AS d USING (delivery_id)
        WHERE d.supplier_id <> v_supplier_id
           OR result.total_cost IS DISTINCT FROM
              (d.quantity::numeric * d.unit_cost)::numeric(20, 2)
    ) THEN
        RAISE EXCEPTION 'fn_supplier_deliveries returned inconsistent data';
    END IF;
END;
$$;

-- Проверка задания 3: многооператорная табличная функция.
DO $$
DECLARE
    v_warehouse_id bigint;
    v_from timestamp without time zone;
    v_to timestamp without time zone;
    v_expected_count bigint;
    v_actual_count bigint;
    v_expected_cost numeric(20, 2);
    v_actual_cost numeric(20, 2);
BEGIN
    SELECT
        d.warehouse_id,
        min(d.delivered_at),
        max(d.delivered_at) + interval '1 second'
    INTO v_warehouse_id, v_from, v_to
    FROM public.deliveries AS d
    GROUP BY d.warehouse_id
    ORDER BY count(*) DESC, d.warehouse_id
    LIMIT 1;

    SELECT
        count(DISTINCT d.product_id),
        sum(d.quantity::numeric * d.unit_cost)::numeric(20, 2)
    INTO v_expected_count, v_expected_cost
    FROM public.deliveries AS d
    WHERE d.warehouse_id = v_warehouse_id
      AND d.delivered_at >= v_from
      AND d.delivered_at < v_to;

    SELECT
        count(*),
        sum(result.total_cost)::numeric(20, 2)
    INTO v_actual_count, v_actual_cost
    FROM public.fn_warehouse_product_summary(
        v_warehouse_id,
        v_from,
        v_to
    ) AS result;

    IF v_actual_count <> v_expected_count
       OR v_actual_cost IS DISTINCT FROM v_expected_cost THEN
        RAISE EXCEPTION
            'fn_warehouse_product_summary returned count/cost %/%, expected %/%',
            v_actual_count, v_actual_cost, v_expected_count, v_expected_cost;
    END IF;

    BEGIN
        PERFORM *
        FROM public.fn_warehouse_product_summary(
            v_warehouse_id,
            v_to,
            v_from
        );
        RAISE EXCEPTION
            'fn_warehouse_product_summary accepted an invalid period';
    EXCEPTION
        WHEN SQLSTATE '22007' THEN
            NULL;
    END;
END;
$$;

-- Проверка задания 4: рекурсивная функция с рекурсивным ОТВ.
DO $$
DECLARE
    v_root_section_id bigint;
    v_expected_count bigint;
    v_actual_count bigint;
BEGIN
    SELECT root.section_id
    INTO v_root_section_id
    FROM public.warehouse_sections AS root
    WHERE root.parent_section_id IS NULL
      AND EXISTS (
          SELECT 1
          FROM public.warehouse_sections AS child
          WHERE child.warehouse_id = root.warehouse_id
            AND child.parent_section_id = root.section_id
      )
    ORDER BY root.section_id
    LIMIT 1;

    WITH RECURSIVE expected_tree AS (
        SELECT
            ws.section_id,
            ws.warehouse_id,
            ARRAY[ws.section_id]::bigint[] AS path_ids
        FROM public.warehouse_sections AS ws
        WHERE ws.section_id = v_root_section_id

        UNION ALL

        SELECT
            child.section_id,
            child.warehouse_id,
            parent.path_ids || child.section_id
        FROM public.warehouse_sections AS child
        JOIN expected_tree AS parent
          ON child.warehouse_id = parent.warehouse_id
         AND child.parent_section_id = parent.section_id
        WHERE NOT child.section_id = ANY(parent.path_ids)
    )
    SELECT count(*)
    INTO v_expected_count
    FROM expected_tree;

    SELECT count(*)
    INTO v_actual_count
    FROM public.fn_section_tree(v_root_section_id);

    IF v_actual_count <> v_expected_count THEN
        RAISE EXCEPTION 'fn_section_tree returned % rows, expected %',
            v_actual_count, v_expected_count;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.fn_section_tree(v_root_section_id) AS tree
        WHERE tree.path_ids[1] <> v_root_section_id
           OR tree.depth <> cardinality(tree.path_ids) - 1
    ) THEN
        RAISE EXCEPTION 'fn_section_tree returned an invalid path or depth';
    END IF;

    IF (
        SELECT count(DISTINCT tree.warehouse_id)
        FROM public.fn_section_tree(v_root_section_id) AS tree
    ) <> 1 THEN
        RAISE EXCEPTION 'fn_section_tree crossed a warehouse boundary';
    END IF;

    BEGIN
        PERFORM * FROM public.fn_section_tree(-1);
        RAISE EXCEPTION 'fn_section_tree accepted an unknown section';
    EXCEPTION
        WHEN SQLSTATE 'P0002' THEN
            NULL;
    END;
END;
$$;

-- Проверка задания 5: хранимая процедура с параметрами.
DO $$
DECLARE
    v_supplier_id bigint;
    v_inactive_supplier_id bigint;
    v_product_id bigint;
    v_perishable_product_id bigint;
    v_warehouse_id bigint;
    v_delivery_id bigint;
    v_duplicate_id bigint;
    v_invalid_id bigint;
BEGIN
    SELECT s.supplier_id
    INTO v_supplier_id
    FROM public.suppliers AS s
    WHERE s.is_active
    ORDER BY s.supplier_id
    LIMIT 1;

    SELECT p.product_id
    INTO v_product_id
    FROM public.products AS p
    WHERE NOT p.is_perishable
    ORDER BY p.product_id
    LIMIT 1;

    SELECT p.product_id
    INTO v_perishable_product_id
    FROM public.products AS p
    WHERE p.is_perishable
    ORDER BY p.product_id
    LIMIT 1;

    SELECT w.warehouse_id
    INTO v_warehouse_id
    FROM public.warehouses AS w
    ORDER BY w.warehouse_id
    LIMIT 1;

    CALL public.sp_register_delivery(
        v_supplier_id,
        v_product_id,
        v_warehouse_id,
        timestamp '2026-09-11 12:00:00',
        7,
        12.34,
        'LR3-PROC-0001',
        'inspection',
        NULL,
        v_delivery_id
    );

    IF NOT EXISTS (
        SELECT 1
        FROM public.deliveries AS d
        WHERE d.delivery_id = v_delivery_id
          AND d.batch_number = 'LR3-PROC-0001'
    ) THEN
        RAISE EXCEPTION 'sp_register_delivery did not create the delivery';
    END IF;

    BEGIN
        CALL public.sp_register_delivery(
            v_supplier_id,
            v_product_id,
            v_warehouse_id,
            timestamp '2026-09-11 12:00:00',
            7,
            12.34,
            'LR3-PROC-0001',
            'inspection',
            NULL,
            v_duplicate_id
        );
        RAISE EXCEPTION 'sp_register_delivery accepted a duplicate business key';
    EXCEPTION
        WHEN unique_violation THEN
            NULL;
    END;

    INSERT INTO public.suppliers (
        name,
        tax_id,
        country,
        city,
        email,
        phone,
        rating,
        is_active,
        created_at
    )
    VALUES (
        'LR3 inactive supplier',
        'LR3INACTIVE',
        'Russia',
        'Moscow',
        'lr3-inactive@example.com',
        '+70000000000',
        3.00,
        false,
        date '2026-09-11'
    )
    RETURNING supplier_id INTO v_inactive_supplier_id;

    BEGIN
        CALL public.sp_register_delivery(
            v_inactive_supplier_id,
            v_product_id,
            v_warehouse_id,
            timestamp '2026-09-11 12:00:00',
            1,
            1.00,
            'LR3-PROC-0002',
            'inspection',
            NULL,
            v_invalid_id
        );
        RAISE EXCEPTION 'sp_register_delivery accepted an inactive supplier';
    EXCEPTION
        WHEN SQLSTATE 'P0001' THEN
            NULL;
    END;

    BEGIN
        CALL public.sp_register_delivery(
            v_supplier_id,
            v_perishable_product_id,
            v_warehouse_id,
            timestamp '2026-09-11 12:00:00',
            1,
            1.00,
            'LR3-PROC-0003',
            'inspection',
            date '2026-09-10',
            v_invalid_id
        );
        RAISE EXCEPTION 'sp_register_delivery accepted an invalid expiry date';
    EXCEPTION
        WHEN SQLSTATE '22007' THEN
            NULL;
    END;
END;
$$;

-- Проверка заданий 6 и 9: рекурсивная процедура и DML-триггер AFTER.
DO $$
DECLARE
    v_warehouse_id bigint;
    v_root_id bigint;
    v_child_id bigint;
    v_grandchild_id bigint;
    v_unrelated_id bigint;
    v_unrelated_active boolean;
BEGIN
    SELECT w.warehouse_id
    INTO v_warehouse_id
    FROM public.warehouses AS w
    ORDER BY w.warehouse_id
    LIMIT 1;

    SELECT ws.section_id, ws.is_active
    INTO v_unrelated_id, v_unrelated_active
    FROM public.warehouse_sections AS ws
    WHERE ws.warehouse_id = v_warehouse_id
    ORDER BY ws.section_id
    LIMIT 1;

    INSERT INTO public.warehouse_sections (
        warehouse_id,
        parent_section_id,
        code,
        name,
        section_type,
        capacity_m3,
        floor,
        is_active
    )
    VALUES (
        v_warehouse_id,
        NULL,
        'LR3-TEST-ROOT',
        'LR3 test root',
        'storage',
        10.00,
        0,
        true
    )
    RETURNING section_id INTO v_root_id;

    INSERT INTO public.warehouse_sections (
        warehouse_id,
        parent_section_id,
        code,
        name,
        section_type,
        capacity_m3,
        floor,
        is_active
    )
    VALUES (
        v_warehouse_id,
        v_root_id,
        'LR3-TEST-CHILD',
        'LR3 test child',
        'storage',
        10.00,
        0,
        true
    )
    RETURNING section_id INTO v_child_id;

    INSERT INTO public.warehouse_sections (
        warehouse_id,
        parent_section_id,
        code,
        name,
        section_type,
        capacity_m3,
        floor,
        is_active
    )
    VALUES (
        v_warehouse_id,
        v_child_id,
        'LR3-TEST-GRANDCHILD',
        'LR3 test grandchild',
        'storage',
        10.00,
        0,
        true
    )
    RETURNING section_id INTO v_grandchild_id;

    CALL public.sp_set_section_subtree_active(v_root_id, false);

    IF (
        SELECT count(*)
        FROM public.warehouse_sections AS ws
        WHERE ws.section_id IN (v_root_id, v_child_id, v_grandchild_id)
          AND NOT ws.is_active
    ) <> 3 THEN
        RAISE EXCEPTION
            'sp_set_section_subtree_active did not update the complete subtree';
    END IF;

    IF (
        SELECT ws.is_active
        FROM public.warehouse_sections AS ws
        WHERE ws.section_id = v_unrelated_id
    ) IS DISTINCT FROM v_unrelated_active THEN
        RAISE EXCEPTION
            'sp_set_section_subtree_active modified an unrelated section';
    END IF;

    BEGIN
        UPDATE public.warehouse_sections
        SET parent_section_id = v_grandchild_id
        WHERE section_id = v_root_id;
        RAISE EXCEPTION
            'trg_warehouse_sections_no_cycle allowed an indirect cycle';
    EXCEPTION
        WHEN SQLSTATE 'P0001' THEN
            NULL;
    END;

    IF (
        SELECT ws.parent_section_id
        FROM public.warehouse_sections AS ws
        WHERE ws.section_id = v_root_id
    ) IS NOT NULL THEN
        RAISE EXCEPTION
            'trg_warehouse_sections_no_cycle did not roll back the invalid update';
    END IF;
END;
$$;

-- Проверка задания 8: хранимая процедура доступа к метаданным.
DO $$
DECLARE
    v_metadata jsonb;
BEGIN
    CALL public.sp_describe_table('deliveries', v_metadata);

    IF v_metadata ->> 'schema' <> 'public'
       OR v_metadata ->> 'name' <> 'deliveries'
       OR v_metadata ->> 'object_type' <> 'BASE TABLE'
       OR jsonb_array_length(v_metadata -> 'columns') <> 10
       OR jsonb_array_length(v_metadata -> 'constraints') = 0 THEN
        RAISE EXCEPTION 'sp_describe_table returned incomplete metadata: %',
            v_metadata;
    END IF;

    BEGIN
        CALL public.sp_describe_table('lr3_missing_table', v_metadata);
        RAISE EXCEPTION 'sp_describe_table accepted an unknown table';
    EXCEPTION
        WHEN SQLSTATE 'P0002' THEN
            NULL;
    END;
END;
$$;

-- Проверка задания 10: DML-триггер INSTEAD OF.
DO $$
DECLARE
    v_supplier_tax_id varchar(12);
    v_supplier_name varchar(120);
    v_product_sku varchar(20);
    v_warehouse_code varchar(16);
    v_delivery_id bigint;
    v_returned_supplier_name varchar(120);
BEGIN
    SELECT s.tax_id, s.name
    INTO v_supplier_tax_id, v_supplier_name
    FROM public.suppliers AS s
    ORDER BY s.supplier_id
    LIMIT 1;

    SELECT p.sku
    INTO v_product_sku
    FROM public.products AS p
    ORDER BY p.product_id
    LIMIT 1;

    SELECT w.code
    INTO v_warehouse_code
    FROM public.warehouses AS w
    ORDER BY w.warehouse_id
    LIMIT 1;

    INSERT INTO public.v_delivery_entry (
        supplier_tax_id,
        product_sku,
        warehouse_code,
        delivered_at,
        quantity,
        unit_cost,
        batch_number,
        quality_status,
        expires_on
    )
    VALUES (
        v_supplier_tax_id,
        v_product_sku,
        v_warehouse_code,
        timestamp '2026-09-11 13:00:00',
        5,
        10.00,
        'LR3-VIEW-0001',
        'inspection',
        NULL
    )
    RETURNING delivery_id, supplier_name
    INTO v_delivery_id, v_returned_supplier_name;

    IF v_returned_supplier_name IS DISTINCT FROM v_supplier_name
       OR NOT EXISTS (
           SELECT 1
           FROM public.deliveries AS d
           WHERE d.delivery_id = v_delivery_id
             AND d.quantity = 5
       ) THEN
        RAISE EXCEPTION
            'trg_v_delivery_entry_dml did not insert or canonicalize the row';
    END IF;

    UPDATE public.v_delivery_entry
    SET quantity = 9,
        quality_status = 'accepted'
    WHERE delivery_id = v_delivery_id;

    IF NOT EXISTS (
        SELECT 1
        FROM public.deliveries AS d
        WHERE d.delivery_id = v_delivery_id
          AND d.quantity = 9
          AND d.quality_status = 'accepted'
    ) THEN
        RAISE EXCEPTION 'trg_v_delivery_entry_dml did not update the base row';
    END IF;

    DELETE FROM public.v_delivery_entry
    WHERE delivery_id = v_delivery_id;

    IF EXISTS (
        SELECT 1
        FROM public.deliveries AS d
        WHERE d.delivery_id = v_delivery_id
    ) THEN
        RAISE EXCEPTION 'trg_v_delivery_entry_dml did not delete the base row';
    END IF;

    BEGIN
        INSERT INTO public.v_delivery_entry (
            supplier_tax_id,
            product_sku,
            warehouse_code,
            delivered_at,
            quantity,
            unit_cost,
            batch_number,
            quality_status
        )
        VALUES (
            'MISSING',
            v_product_sku,
            v_warehouse_code,
            timestamp '2026-09-11 13:00:00',
            1,
            1.00,
            'LR3-VIEW-0002',
            'inspection'
        );
        RAISE EXCEPTION
            'trg_v_delivery_entry_dml accepted an unknown supplier';
    EXCEPTION
        WHEN SQLSTATE 'P0002' THEN
            NULL;
    END;
END;
$$;

-- Проверка дополнительной функции статистики самых нагруженных складов.
DO $$
DECLARE
    v_supplier_id bigint;
    v_product_id bigint;
    v_warehouse_ids bigint[];
    v_actual_warehouses bigint[];
    v_expected_stats jsonb;
    v_actual_stats jsonb;
    v_stored_stats jsonb;
    v_stats_count bigint;
    v_top_warehouse_id bigint;
    v_table_name text := format(
        'warehouse_daily_stats_%s',
        to_char(current_date - 1, 'YYYY_MM_DD')
    );
BEGIN
    SELECT s.supplier_id
    INTO v_supplier_id
    FROM public.suppliers AS s
    ORDER BY s.supplier_id
    LIMIT 1;

    SELECT p.product_id
    INTO v_product_id
    FROM public.products AS p
    ORDER BY p.product_id
    LIMIT 1;

    SELECT array_agg(selected.warehouse_id ORDER BY selected.warehouse_id)
    INTO v_warehouse_ids
    FROM (
        SELECT w.warehouse_id
        FROM public.warehouses AS w
        ORDER BY w.warehouse_id
        LIMIT 3
    ) AS selected;

    IF cardinality(v_warehouse_ids) <> 3 THEN
        RAISE EXCEPTION 'Test data must contain at least three warehouses';
    END IF;

    -- Изолируем расчёт от существующих поставок за вчера. Весь тест выполняется
    -- во внешней транзакции и завершается ROLLBACK.
    DELETE FROM public.deliveries AS d
    WHERE d.delivered_at >= (current_date - 1)::timestamp
      AND d.delivered_at < current_date::timestamp;

    -- Таблица могла остаться после установочного вызова функции. Удаляем её в
    -- тестовой транзакции, чтобы проверить именно создание нового снимка.
    EXECUTE format('DROP TABLE IF EXISTS public.%I', v_table_name);

    IF to_regclass(format('public.%I', v_table_name)) IS NOT NULL THEN
        RAISE EXCEPTION 'Failed to remove test statistics table %',
            v_table_name;
    END IF;

    -- Первый склад получает три поставки. У второго и третьего по две
    -- поставки, поэтому их взаимный порядок должен определяться суммарным
    -- количеством: 30 у второго против 20 у третьего.
    INSERT INTO public.deliveries (
        supplier_id,
        product_id,
        warehouse_id,
        delivered_at,
        quantity,
        unit_cost,
        batch_number,
        quality_status,
        expires_on
    )
    SELECT
        v_supplier_id,
        v_product_id,
        v_warehouse_ids[fixture.warehouse_position],
        (current_date - 1)::timestamp
            + time '12:00:00'
            + make_interval(secs => fixture.sequence_number),
        fixture.quantity,
        10.00,
        format(
            'LR3-STAT-%s-%s',
            fixture.warehouse_position,
            fixture.sequence_number
        ),
        'accepted',
        NULL
    FROM (
        VALUES
            (1, 1, 5),
            (1, 2, 5),
            (1, 3, 5),
            (2, 1, 20),
            (2, 2, 10),
            (3, 1, 10),
            (3, 2, 10)
    ) AS fixture(warehouse_position, sequence_number, quantity);

    WITH warehouse_load AS (
        SELECT
            (current_date - 1)::date AS stat_date,
            d.warehouse_id,
            w.code AS warehouse_code,
            w.name AS warehouse_name,
            count(*)::bigint AS delivery_count,
            sum(d.quantity)::bigint AS total_quantity,
            sum(d.quantity::numeric * d.unit_cost)::numeric(20, 2)
                AS total_cost
        FROM public.deliveries AS d
        JOIN public.warehouses AS w ON w.warehouse_id = d.warehouse_id
        WHERE d.delivered_at >= (current_date - 1)::timestamp
          AND d.delivered_at < current_date::timestamp
        GROUP BY d.warehouse_id, w.code, w.name
    ),
    ranked_warehouses AS (
        SELECT
            load.*,
            row_number() OVER (
                ORDER BY
                    load.delivery_count DESC,
                    load.total_quantity DESC,
                    load.warehouse_id
            )::integer AS load_rank
        FROM warehouse_load AS load
    )
    SELECT jsonb_agg(to_jsonb(ranked) ORDER BY ranked.load_rank)
    INTO v_expected_stats
    FROM ranked_warehouses AS ranked
    WHERE ranked.load_rank <= 2;

    SELECT
        jsonb_agg(to_jsonb(stats) ORDER BY stats.load_rank),
        array_agg(stats.warehouse_id ORDER BY stats.load_rank)
    INTO v_actual_stats, v_actual_warehouses
    FROM public.fn_refresh_yesterday_warehouse_stats(2) AS stats;

    IF v_actual_stats IS DISTINCT FROM v_expected_stats THEN
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats returned %, expected %',
            v_actual_stats,
            v_expected_stats;
    END IF;

    IF v_actual_warehouses IS DISTINCT FROM
       ARRAY[v_warehouse_ids[1], v_warehouse_ids[2]] THEN
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats violated ranking rules: %',
            v_actual_warehouses;
    END IF;

    IF to_regclass(format('public.%I', v_table_name)) IS NULL THEN
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats did not create table %',
            v_table_name;
    END IF;

    -- Повторный вызов должен заменить содержимое снимка теми же строками, а
    -- не добавить дубликаты.
    PERFORM * FROM public.fn_refresh_yesterday_warehouse_stats(2);

    EXECUTE format(
        $query$
        SELECT jsonb_agg(to_jsonb(stored) ORDER BY stored.load_rank)
        FROM (
            SELECT
                stat_date,
                warehouse_id,
                warehouse_code,
                warehouse_name,
                delivery_count,
                total_quantity,
                total_cost,
                load_rank
            FROM public.%I
        ) AS stored
        $query$,
        v_table_name
    )
    INTO v_stored_stats;

    IF v_stored_stats IS DISTINCT FROM v_expected_stats THEN
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats is not idempotent: %',
            v_stored_stats;
    END IF;

    SELECT count(*), min(stats.warehouse_id)
    INTO v_stats_count, v_top_warehouse_id
    FROM public.fn_refresh_yesterday_warehouse_stats(1) AS stats;

    IF v_stats_count <> 1
       OR v_top_warehouse_id IS DISTINCT FROM v_warehouse_ids[1] THEN
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats did not apply limit 1';
    END IF;

    EXECUTE format('SELECT count(*) FROM public.%I', v_table_name)
    INTO v_stats_count;

    IF v_stats_count <> 1 THEN
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats did not apply a new limit';
    END IF;

    BEGIN
        PERFORM * FROM public.fn_refresh_yesterday_warehouse_stats(0);
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats accepted an invalid limit';
    EXCEPTION
        WHEN SQLSTATE '22023' THEN
            NULL;
    END;

    BEGIN
        PERFORM * FROM public.fn_refresh_yesterday_warehouse_stats(NULL);
        RAISE EXCEPTION
            'fn_refresh_yesterday_warehouse_stats accepted a NULL limit';
    EXCEPTION
        WHEN SQLSTATE '22023' THEN
            NULL;
    END;

    EXECUTE format('SELECT count(*) FROM public.%I', v_table_name)
    INTO v_stats_count;

    IF v_stats_count <> 1 THEN
        RAISE EXCEPTION
            'invalid limits modified the existing statistics snapshot';
    END IF;
END;
$$;

-- Проверка задания 7: наличие данных для процедуры с курсором.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.deliveries AS d
        WHERE d.quality_status = 'accepted'
          AND d.expires_on IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Test data has no expiring accepted deliveries';
    END IF;
END;
$$;

SELECT min(d.expires_on) AS lr3_cursor_date
FROM public.deliveries AS d
WHERE d.quality_status = 'accepted'
  AND d.expires_on IS NOT NULL
\gset

-- Проверка задания 7: открытие и чтение refcursor в явной транзакции.
CALL public.sp_open_expiring_deliveries(
    :'lr3_cursor_date'::date,
    :'lr3_cursor_date'::date,
    'lr3_expiring_cursor'
);

FETCH ALL FROM lr3_expiring_cursor;
\unset lr3_cursor_date

ROLLBACK;
