\set ON_ERROR_STOP on
\connect supply_lab

-- Задание 1. Разработать скалярную функцию.
-- Функция вычисляет полную стоимость одной поставки как произведение
-- количества товара на закупочную стоимость единицы.
CREATE OR REPLACE FUNCTION public.fn_delivery_total(p_delivery_id bigint)
RETURNS numeric(20, 2)
LANGUAGE plpgsql
STABLE
STRICT
AS $$
DECLARE
    v_total numeric(20, 2);
BEGIN
    SELECT (d.quantity::numeric * d.unit_cost)::numeric(20, 2)
    INTO v_total
    FROM public.deliveries AS d
    WHERE d.delivery_id = p_delivery_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Delivery with id % does not exist', p_delivery_id
            USING ERRCODE = 'P0002';
    END IF;

    RETURN v_total;
END;
$$;

-- Задание 2. Разработать подставляемую табличную функцию.
-- SQL-функция одним запросом возвращает поставки выбранного поставщика
-- вместе с данными товаров, складов и вычисленной стоимостью поставок.
CREATE OR REPLACE FUNCTION public.fn_supplier_deliveries(p_supplier_id bigint)
RETURNS TABLE (
    delivery_id bigint,
    product_id bigint,
    product_sku varchar(20),
    product_name varchar(160),
    warehouse_id bigint,
    warehouse_code varchar(16),
    delivered_at timestamp without time zone,
    quantity integer,
    unit_cost numeric(12, 2),
    total_cost numeric(20, 2),
    quality_status varchar(16),
    expires_on date
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        d.delivery_id,
        p.product_id,
        p.sku,
        p.name,
        w.warehouse_id,
        w.code,
        d.delivered_at,
        d.quantity,
        d.unit_cost,
        (d.quantity::numeric * d.unit_cost)::numeric(20, 2),
        d.quality_status,
        d.expires_on
    FROM public.deliveries AS d
    JOIN public.products AS p ON p.product_id = d.product_id
    JOIN public.warehouses AS w ON w.warehouse_id = d.warehouse_id
    WHERE d.supplier_id = p_supplier_id
    ORDER BY d.delivered_at, d.delivery_id
$$;

-- Задание 3. Разработать многооператорную табличную функцию.
-- PL/pgSQL-функция проверяет склад и временной интервал, после чего возвращает
-- агрегированную статистику поставок по товарам.
CREATE OR REPLACE FUNCTION public.fn_warehouse_product_summary(
    p_warehouse_id bigint,
    p_from timestamp without time zone,
    p_to timestamp without time zone
)
RETURNS TABLE (
    product_id bigint,
    sku varchar(20),
    product_name varchar(160),
    delivery_count bigint,
    total_quantity bigint,
    total_cost numeric(20, 2)
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.warehouses AS w
        WHERE w.warehouse_id = p_warehouse_id
    ) THEN
        RAISE EXCEPTION 'Warehouse with id % does not exist', p_warehouse_id
            USING ERRCODE = 'P0002';
    END IF;

    IF p_from IS NULL OR p_to IS NULL OR p_from >= p_to THEN
        RAISE EXCEPTION 'Invalid period: p_from (%) must be earlier than p_to (%)',
            p_from, p_to
            USING ERRCODE = '22007';
    END IF;

    RETURN QUERY
    SELECT
        p.product_id,
        p.sku,
        p.name,
        count(*)::bigint,
        sum(d.quantity)::bigint,
        sum(d.quantity::numeric * d.unit_cost)::numeric(20, 2)
    FROM public.deliveries AS d
    JOIN public.products AS p ON p.product_id = d.product_id
    WHERE d.warehouse_id = p_warehouse_id
      AND d.delivered_at >= p_from
      AND d.delivered_at < p_to
    GROUP BY p.product_id, p.sku, p.name
    ORDER BY
        sum(d.quantity::numeric * d.unit_cost) DESC,
        p.product_id;
END;
$$;

-- Задание 4. Разработать рекурсивную функцию или функцию с рекурсивным ОТВ.
-- Функция с WITH RECURSIVE строит дерево складских секций от заданного корня,
-- вычисляет глубину и сохраняет путь до каждой секции.
CREATE OR REPLACE FUNCTION public.fn_section_tree(p_root_section_id bigint)
RETURNS TABLE (
    section_id bigint,
    parent_section_id bigint,
    warehouse_id bigint,
    code varchar(24),
    name varchar(160),
    depth integer,
    path_ids bigint[]
)
LANGUAGE plpgsql
STABLE
STRICT
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

    RETURN QUERY
    WITH RECURSIVE section_tree AS (
        SELECT
            ws.section_id,
            ws.parent_section_id,
            ws.warehouse_id,
            ws.code,
            ws.name,
            0 AS depth,
            ARRAY[ws.section_id]::bigint[] AS path_ids
        FROM public.warehouse_sections AS ws
        WHERE ws.section_id = p_root_section_id
          AND ws.warehouse_id = v_warehouse_id

        UNION ALL

        SELECT
            child.section_id,
            child.parent_section_id,
            child.warehouse_id,
            child.code,
            child.name,
            parent.depth + 1,
            parent.path_ids || child.section_id
        FROM public.warehouse_sections AS child
        JOIN section_tree AS parent
          ON child.warehouse_id = parent.warehouse_id
         AND child.parent_section_id = parent.section_id
        WHERE NOT child.section_id = ANY(parent.path_ids)
    )
    SELECT
        tree.section_id,
        tree.parent_section_id,
        tree.warehouse_id,
        tree.code,
        tree.name,
        tree.depth,
        tree.path_ids
    FROM section_tree AS tree
    ORDER BY tree.path_ids;
END;
$$;

-- Защита. Создать статистическую таблицу вчерашнего дня и
-- сохранить в ней самые нагруженные склады за день.
-- Нагрузка определяется числом поставок. При равном числе поставок выше
-- располагается склад с большим суммарным количеством принятого товара.
CREATE OR REPLACE FUNCTION public.fn_refresh_yesterday_warehouse_stats1(
    p_limit integer DEFAULT 5
)
RETURNS TABLE (
    stat_date date,
    warehouse_id bigint,
    warehouse_code varchar(16),
    warehouse_name varchar(160),
    delivery_count bigint,
    total_quantity bigint,
    total_cost numeric(20, 2),
    load_rank integer
)
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    v_stat_date date := current_date - 1;
    v_table_name text := format(
        'warehouse_daily_stats_%s',
        to_char(current_date - 1, 'YYYY_MM_DD')
    );
BEGIN
    IF p_limit IS NULL OR p_limit <= 0 THEN
        RAISE EXCEPTION 'p_limit must be greater than zero'
            USING ERRCODE = '22023';
    END IF;

    EXECUTE format(
        $create_table$
        CREATE TABLE IF NOT EXISTS public.%I (
            stat_date date NOT NULL,
            warehouse_id bigint NOT NULL PRIMARY KEY,
            warehouse_code varchar(16) NOT NULL,
            warehouse_name varchar(160) NOT NULL,
            delivery_count bigint NOT NULL CHECK (delivery_count > 0),
            total_quantity bigint NOT NULL CHECK (total_quantity > 0),
            total_cost numeric(20, 2) NOT NULL,
            load_rank integer NOT NULL UNIQUE CHECK (load_rank > 0),
            calculated_at timestamp with time zone NOT NULL
                DEFAULT clock_timestamp(),
            FOREIGN KEY (warehouse_id)
                REFERENCES public.warehouses (warehouse_id),
            CHECK (stat_date = %L::date)
        )
        $create_table$,
        v_table_name,
        v_stat_date::text
    );

    EXECUTE format('DELETE FROM public.%I', v_table_name);

    EXECUTE format(
        $insert_stats$
        WITH warehouse_load AS (
            SELECT
                w.warehouse_id,
                w.code AS warehouse_code,
                w.name AS warehouse_name,
                count(*)::bigint AS delivery_count,
                sum(d.quantity)::bigint AS total_quantity,
                sum(d.quantity::numeric * d.unit_cost)::numeric(20, 2)
                    AS total_cost
            FROM public.deliveries AS d
            JOIN public.warehouses AS w ON w.warehouse_id = d.warehouse_id
            WHERE d.delivered_at >= $1::timestamp
              AND d.delivered_at < ($1 + 1)::timestamp
            GROUP BY w.warehouse_id, w.code, w.name
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
        INSERT INTO public.%I (
            stat_date,
            warehouse_id,
            warehouse_code,
            warehouse_name,
            delivery_count,
            total_quantity,
            total_cost,
            load_rank
        )
        SELECT
            $1,
            ranked.warehouse_id,
            ranked.warehouse_code,
            ranked.warehouse_name,
            ranked.delivery_count,
            ranked.total_quantity,
            ranked.total_cost,
            ranked.load_rank
        FROM ranked_warehouses AS ranked
        WHERE ranked.load_rank <= $2
        ORDER BY ranked.load_rank
        $insert_stats$,
        v_table_name
    )
    USING v_stat_date, p_limit;

    RETURN QUERY EXECUTE format(
        $return_stats$
        SELECT
            stats.stat_date,
            stats.warehouse_id,
            stats.warehouse_code,
            stats.warehouse_name,
            stats.delivery_count,
            stats.total_quantity,
            stats.total_cost,
            stats.load_rank
        FROM public.%I AS stats
        ORDER BY stats.load_rank
        $return_stats$,
        v_table_name
    );
END;
$$;

SELECT fn_refresh_yesterday_warehouse_stats();
