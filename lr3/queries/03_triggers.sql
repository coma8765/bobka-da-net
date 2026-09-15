\set ON_ERROR_STOP on
\connect supply_lab

-- Вспомогательное представление для задания 10. Оно показывает поставку с
-- бизнес-идентификаторами и названиями связанных объектов вместо внешних
-- ключей таблицы deliveries.
CREATE OR REPLACE VIEW public.v_delivery_entry AS
SELECT
    d.delivery_id,
    s.tax_id AS supplier_tax_id,
    s.name AS supplier_name,
    p.sku AS product_sku,
    p.name AS product_name,
    w.code AS warehouse_code,
    w.name AS warehouse_name,
    d.delivered_at,
    d.quantity,
    d.unit_cost,
    d.batch_number,
    d.quality_status,
    d.expires_on
FROM public.deliveries AS d
JOIN public.suppliers AS s ON s.supplier_id = d.supplier_id
JOIN public.products AS p ON p.product_id = d.product_id
JOIN public.warehouses AS w ON w.warehouse_id = d.warehouse_id;

-- Задание 9. Разработать DML-триггер AFTER.
-- Триггерная функция после INSERT или изменения родителя проверяет всю
-- цепочку предков складской секции и запрещает косвенные циклы в иерархии.
CREATE OR REPLACE FUNCTION public.tf_warehouse_sections_no_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_has_cycle boolean;
BEGIN
    IF NEW.parent_section_id IS NULL THEN
        RETURN NEW;
    END IF;

    WITH RECURSIVE parent_chain AS (
        SELECT
            ws.section_id,
            ws.parent_section_id,
            ARRAY[ws.section_id]::bigint[] AS path_ids
        FROM public.warehouse_sections AS ws
        WHERE ws.warehouse_id = NEW.warehouse_id
          AND ws.section_id = NEW.parent_section_id

        UNION ALL

        SELECT
            parent.section_id,
            parent.parent_section_id,
            child.path_ids || parent.section_id
        FROM public.warehouse_sections AS parent
        JOIN parent_chain AS child
          ON parent.warehouse_id = NEW.warehouse_id
         AND parent.section_id = child.parent_section_id
        WHERE NOT parent.section_id = ANY(child.path_ids)
    )
    SELECT EXISTS (
        SELECT 1
        FROM parent_chain AS chain
        WHERE chain.section_id = NEW.section_id
    )
    INTO v_has_cycle;

    IF v_has_cycle THEN
        RAISE EXCEPTION
            'Section % cannot use section % as parent because it creates a cycle',
            NEW.section_id, NEW.parent_section_id
            USING ERRCODE = 'P0001';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_warehouse_sections_no_cycle
    ON public.warehouse_sections;

CREATE TRIGGER trg_warehouse_sections_no_cycle
AFTER INSERT OR UPDATE OF warehouse_id, parent_section_id
ON public.warehouse_sections
FOR EACH ROW
EXECUTE FUNCTION public.tf_warehouse_sections_no_cycle();

-- Задание 10. Разработать DML-триггер INSTEAD OF.
-- Триггерная функция обрабатывает INSERT, UPDATE и DELETE над представлением
-- v_delivery_entry и преобразует их в операции над таблицей deliveries.
CREATE OR REPLACE FUNCTION public.tf_v_delivery_entry_dml()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_supplier_id bigint;
    v_supplier_name varchar(120);
    v_product_id bigint;
    v_product_name varchar(160);
    v_warehouse_id bigint;
    v_warehouse_name varchar(160);
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.deliveries AS d
        WHERE d.delivery_id = OLD.delivery_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Delivery with id % does not exist', OLD.delivery_id
                USING ERRCODE = 'P0002';
        END IF;

        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE'
       AND NEW.delivery_id IS DISTINCT FROM OLD.delivery_id THEN
        RAISE EXCEPTION 'delivery_id cannot be changed through v_delivery_entry'
            USING ERRCODE = '22000';
    END IF;

    SELECT s.supplier_id, s.name
    INTO v_supplier_id, v_supplier_name
    FROM public.suppliers AS s
    WHERE s.tax_id = NEW.supplier_tax_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Supplier with tax_id % does not exist',
            NEW.supplier_tax_id
            USING ERRCODE = 'P0002';
    END IF;

    SELECT p.product_id, p.name
    INTO v_product_id, v_product_name
    FROM public.products AS p
    WHERE p.sku = NEW.product_sku;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product with sku % does not exist', NEW.product_sku
            USING ERRCODE = 'P0002';
    END IF;

    SELECT w.warehouse_id, w.name
    INTO v_warehouse_id, v_warehouse_name
    FROM public.warehouses AS w
    WHERE w.code = NEW.warehouse_code;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Warehouse with code % does not exist',
            NEW.warehouse_code
            USING ERRCODE = 'P0002';
    END IF;

    NEW.supplier_name := v_supplier_name;
    NEW.product_name := v_product_name;
    NEW.warehouse_name := v_warehouse_name;

    IF TG_OP = 'INSERT' THEN
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
            v_supplier_id,
            v_product_id,
            v_warehouse_id,
            NEW.delivered_at,
            NEW.quantity,
            NEW.unit_cost,
            NEW.batch_number,
            NEW.quality_status,
            NEW.expires_on
        )
        RETURNING delivery_id INTO NEW.delivery_id;

        RETURN NEW;
    END IF;

    UPDATE public.deliveries AS d
    SET
        supplier_id = v_supplier_id,
        product_id = v_product_id,
        warehouse_id = v_warehouse_id,
        delivered_at = NEW.delivered_at,
        quantity = NEW.quantity,
        unit_cost = NEW.unit_cost,
        batch_number = NEW.batch_number,
        quality_status = NEW.quality_status,
        expires_on = NEW.expires_on
    WHERE d.delivery_id = OLD.delivery_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Delivery with id % does not exist', OLD.delivery_id
            USING ERRCODE = 'P0002';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_v_delivery_entry_dml
    ON public.v_delivery_entry;

CREATE TRIGGER trg_v_delivery_entry_dml
INSTEAD OF INSERT OR UPDATE OR DELETE
ON public.v_delivery_entry
FOR EACH ROW
EXECUTE FUNCTION public.tf_v_delivery_entry_dml();
