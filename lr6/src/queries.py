from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, TypeAlias

from psycopg import Connection

TableResult: TypeAlias = tuple[list[str], list[tuple[Any, ...]]]

STATUSES = frozenset({"accepted", "inspection", "rejected"})
TABLES = frozenset({"suppliers", "products", "warehouses", "warehouse_sections", "deliveries"})


def _table(connection: Connection[tuple[Any, ...]], sql: str, params: Sequence[object] = ()) -> TableResult:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return [column.name for column in cursor.description], cursor.fetchall()


def _positive_id(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 10**8:
        raise ValueError("Идентификатор должен быть положительным bigint.")


def _table_name(value: str) -> None:
    if value not in TABLES:
        raise ValueError("Недопустимое имя таблицы.")


def show_delivery_count_by_status(connection: Connection[tuple[Any, ...]], status: str) -> int:
    if status not in STATUSES:
        raise ValueError("Недопустимый статус поставки.")
    return _table(connection, "SELECT count(*) FROM public.deliveries WHERE quality_status = %s", (status,))[1][0][0]


def show_recent_deliveries(connection: Connection[tuple[Any, ...]], limit: int) -> TableResult:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Лимит должен быть целым числом от 1 до 100.")
    return _table(
        connection,
        """
        SELECT d.delivery_id, s.supplier_id, s.name AS supplier_name,
               p.product_id, p.name AS product_name,
               w.warehouse_id, w.name AS warehouse_name,
               d.delivered_at, d.quantity, d.quantity * d.unit_cost AS total_cost
        FROM public.deliveries AS d
        JOIN public.suppliers AS s ON s.supplier_id = d.supplier_id
        JOIN public.products AS p ON p.product_id = d.product_id
        JOIN public.warehouses AS w ON w.warehouse_id = d.warehouse_id
        ORDER BY d.delivered_at DESC, d.delivery_id DESC
        LIMIT %s
    """,
        (limit,),
    )


def show_supplier_cost_rating(connection: Connection[tuple[Any, ...]], date_from: date, date_to: date) -> TableResult:
    if type(date_from) is not date or type(date_to) is not date or date_from >= date_to:
        raise ValueError("Начальная дата должна предшествовать конечной.")
    return _table(
        connection,
        """
        WITH supplier_totals AS (
            SELECT s.supplier_id, s.name AS supplier_name,
                   sum(d.quantity * d.unit_cost) AS total_cost
            FROM public.deliveries AS d
            JOIN public.suppliers AS s ON s.supplier_id = d.supplier_id
            WHERE d.delivered_at >= %s AND d.delivered_at < %s
            GROUP BY s.supplier_id, s.name
        )
        SELECT supplier_id, supplier_name, total_cost,
               dense_rank() OVER (ORDER BY total_cost DESC) AS cost_rank,
               100.0 * total_cost / NULLIF(sum(total_cost) OVER (), 0) AS share_percent,
               sum(total_cost) OVER (
                   ORDER BY total_cost DESC, supplier_id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS cumulative_cost
        FROM supplier_totals
        ORDER BY total_cost DESC, supplier_id
    """,
        (date_from, date_to),
    )


def describe_columns(connection: Connection[tuple[Any, ...]], table_name: str) -> TableResult:
    _table_name(table_name)
    return _table(
        connection,
        """
        SELECT ordinal_position, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """,
        (table_name,),
    )


def show_delivery_total(connection: Connection[tuple[Any, ...]], delivery_id: int) -> Decimal:
    _positive_id(delivery_id)
    with connection.transaction():
        return _table(connection, "SELECT public.fn_delivery_total(%s)", (delivery_id,))[1][0][0]


def show_supplier_deliveries(connection: Connection[tuple[Any, ...]], supplier_id: int) -> TableResult:
    _positive_id(supplier_id)
    return _table(
        connection,
        """
        SELECT * FROM public.fn_supplier_deliveries(%s)
        ORDER BY delivered_at DESC, delivery_id DESC
        LIMIT 100
    """,
        (supplier_id,),
    )


def describe_table_with_procedure(connection: Connection[tuple[Any, ...]], table_name: str) -> dict[str, Any]:
    _table_name(table_name)
    with connection.transaction():
        return _table(connection, "CALL public.sp_describe_table(%s, NULL::jsonb)", (table_name,))[1][0][0]


def show_server_info(connection: Connection[tuple[Any, ...]]) -> TableResult:
    return _table(connection, "SELECT current_database(), session_user, current_schema(), version()")


def create_delivery_notes_table(connection: Connection[tuple[Any, ...]]) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS lr6")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lr6.delivery_notes (
                    note_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    delivery_id bigint NOT NULL REFERENCES public.deliveries (delivery_id),
                    note_text text NOT NULL CHECK (btrim(note_text) <> ''),
                    created_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
                    created_by text NOT NULL DEFAULT session_user
                )
            """)


def add_delivery_note(connection: Connection[tuple[Any, ...]], delivery_id: int, note_text: str) -> TableResult:
    _positive_id(delivery_id)
    if not isinstance(note_text, str) or not note_text.strip():
        raise ValueError("Заметка не должна быть пустой.")
    with connection.transaction():
        return _table(
            connection,
            """
            INSERT INTO lr6.delivery_notes (delivery_id, note_text)
            VALUES (%s, %s)
            RETURNING note_id, delivery_id, note_text, created_at, created_by
        """,
            (delivery_id, note_text),
        )



# def refresh_yesterday_warehouse_stats(connection: Connection[tuple[Any, ...]]) -> TableResult:
#     with connection.transaction():
#         return _table(
#             connection,
#             """
#             SELECT fn_refresh_yesterday_warehouse_stats();
#         """,
#             (),
#         )


