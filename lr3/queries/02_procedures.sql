\set ON_ERROR_STOP on
\connect supply_lab

-- Задание 5. Разработать хранимую процедуру без параметров или с параметрами.
-- Процедура с параметрами проверяет справочники и бизнес-правила, добавляет
-- новую поставку и возвращает её идентификатор через INOUT-параметр.
CREATE OR REPLACE PROCEDURE public.sp_register_delivery(
    p_supplier_id bigint,
    p_product_id bigint,
    p_warehouse_id bigint,
    p_delivered_at timestamp without time zone,
    p_quantity integer,
    p_unit_cost numeric(12, 2),
    p_batch_number varchar(20),
    p_quality_status varchar(16),
    p_expires_on date,
    INOUT p_delivery_id bigint DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_supplier_active boolean;
    v_product_is_perishable boolean;
BEGIN
    SELECT s.is_active
    INTO v_supplier_active
    FROM public.suppliers AS s
    WHERE s.supplier_id = p_supplier_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Supplier with id % does not exist', p_supplier_id
            USING ERRCODE = 'P0002';
    END IF;

    IF NOT v_supplier_active THEN
        RAISE EXCEPTION 'Supplier with id % is inactive', p_supplier_id
            USING ERRCODE = 'P0001';
    END IF;

    SELECT p.is_perishable
    INTO v_product_is_perishable
    FROM public.products AS p
    WHERE p.product_id = p_product_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product with id % does not exist', p_product_id
            USING ERRCODE = 'P0002';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.warehouses AS w
        WHERE w.warehouse_id = p_warehouse_id
    ) THEN
        RAISE EXCEPTION 'Warehouse with id % does not exist', p_warehouse_id
            USING ERRCODE = 'P0002';
    END IF;

    IF v_product_is_perishable
       AND (p_expires_on IS NULL OR p_expires_on < p_delivered_at::date) THEN
        RAISE EXCEPTION
            'Perishable product % must expire on or after the delivery date',
            p_product_id
            USING ERRCODE = '22007';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.deliveries AS d
        WHERE d.supplier_id = p_supplier_id
          AND d.product_id = p_product_id
          AND d.warehouse_id = p_warehouse_id
          AND d.batch_number = p_batch_number
    ) THEN
        RAISE EXCEPTION
            'Delivery with the same supplier, product, warehouse and batch already exists'
            USING ERRCODE = '23505';
    END IF;

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
    VALUES (
        p_supplier_id,
        p_product_id,
        p_warehouse_id,
        p_delivered_at,
        p_quantity,
        p_unit_cost,
        p_batch_number,
        p_quality_status,
        p_expires_on
    )
    RETURNING delivery_id INTO p_delivery_id;
END;
$$;

-- Задание 6. Разработать рекурсивную хранимую процедуру или процедуру с
-- рекурсивным ОТВ.
-- Процедура с WITH RECURSIVE изменяет признак активности корневой складской
-- секции и всех её потомков, не выходя за границы склада.
CREATE OR REPLACE PROCEDURE public.sp_set_section_subtree_active(
    p_root_section_id bigint,
    p_is_active boolean
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_warehouse_id bigint;
BEGIN
    SELECT ws.warehouse_id
    INTO v_warehouse_id
    FROM public.warehouse_sections AS ws
    WHERE ws.section_id = p_root_section_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Warehouse section with id % does not exist',
            p_root_section_id
            USING ERRCODE = 'P0002';
    END IF;

    WITH RECURSIVE section_tree AS (
        SELECT
            ws.section_id,
            ws.warehouse_id,
            ARRAY[ws.section_id]::bigint[] AS path_ids
        FROM public.warehouse_sections AS ws
        WHERE ws.section_id = p_root_section_id
          AND ws.warehouse_id = v_warehouse_id

        UNION ALL

        SELECT
            child.section_id,
            child.warehouse_id,
            parent.path_ids || child.section_id
        FROM public.warehouse_sections AS child
        JOIN section_tree AS parent
          ON child.warehouse_id = parent.warehouse_id
         AND child.parent_section_id = parent.section_id
        WHERE NOT child.section_id = ANY(parent.path_ids)
    )
    UPDATE public.warehouse_sections AS ws
    SET is_active = p_is_active
    FROM section_tree AS tree
    WHERE ws.section_id = tree.section_id
      AND ws.warehouse_id = tree.warehouse_id;
END;
$$;

-- Задание 7. Разработать хранимую процедуру с курсором.
-- Процедура открывает переданный refcursor со списком принятых поставок,
-- срок годности которых входит в заданный диапазон дат.
CREATE OR REPLACE PROCEDURE public.sp_open_expiring_deliveries(
    p_from date,
    p_to date,
    INOUT p_cursor refcursor DEFAULT 'expiring_deliveries'
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_from IS NULL OR p_to IS NULL OR p_from > p_to THEN
        RAISE EXCEPTION 'Invalid date range: p_from (%) must not exceed p_to (%)',
            p_from, p_to
            USING ERRCODE = '22007';
    END IF;

    OPEN p_cursor FOR
        SELECT
            d.delivery_id,
            s.supplier_id,
            s.name AS supplier_name,
            p.product_id,
            p.name AS product_name,
            w.warehouse_id,
            w.name AS warehouse_name,
            d.batch_number,
            d.delivered_at,
            d.quantity,
            d.expires_on
        FROM public.deliveries AS d
        JOIN public.suppliers AS s ON s.supplier_id = d.supplier_id
        JOIN public.products AS p ON p.product_id = d.product_id
        JOIN public.warehouses AS w ON w.warehouse_id = d.warehouse_id
        WHERE d.quality_status = 'accepted'
          AND d.expires_on BETWEEN p_from AND p_to
        ORDER BY d.expires_on, d.delivery_id;
END;
$$;

-- Задание 8. Разработать хранимую процедуру доступа к метаданным.
-- Процедура читает information_schema и возвращает в JSON описание столбцов
-- и ограничений указанной таблицы или представления схемы public.
CREATE OR REPLACE PROCEDURE public.sp_describe_table(
    p_table_name text,
    INOUT p_metadata jsonb DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_table_type text;
BEGIN
    SELECT t.table_type
    INTO v_table_type
    FROM information_schema.tables AS t
    WHERE t.table_schema = 'public'
      AND t.table_name = p_table_name;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Table or view public.% does not exist', p_table_name
            USING ERRCODE = 'P0002';
    END IF;

    SELECT jsonb_build_object(
        'schema', 'public',
        'name', p_table_name,
        'object_type', v_table_type,
        'columns', COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'name', c.column_name,
                        'data_type', c.data_type,
                        'is_nullable', c.is_nullable,
                        'default', c.column_default
                    )
                    ORDER BY c.ordinal_position
                )
                FROM information_schema.columns AS c
                WHERE c.table_schema = 'public'
                  AND c.table_name = p_table_name
            ),
            '[]'::jsonb
        ),
        'constraints', COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'name', tc.constraint_name,
                        'type', tc.constraint_type,
                        'columns', COALESCE(
                            (
                                SELECT jsonb_agg(kcu.column_name ORDER BY kcu.ordinal_position)
                                FROM information_schema.key_column_usage AS kcu
                                WHERE kcu.constraint_schema = tc.constraint_schema
                                  AND kcu.constraint_name = tc.constraint_name
                                  AND kcu.table_schema = tc.table_schema
                                  AND kcu.table_name = tc.table_name
                            ),
                            '[]'::jsonb
                        ),
                        'referenced_columns', COALESCE(
                            (
                                SELECT jsonb_agg(ccu.column_name ORDER BY ccu.column_name)
                                FROM information_schema.constraint_column_usage AS ccu
                                WHERE ccu.constraint_schema = tc.constraint_schema
                                  AND ccu.constraint_name = tc.constraint_name
                            ),
                            '[]'::jsonb
                        )
                    )
                    ORDER BY tc.constraint_name
                )
                FROM information_schema.table_constraints AS tc
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = p_table_name
            ),
            '[]'::jsonb
        )
    )
    INTO p_metadata;
END;
$$;
