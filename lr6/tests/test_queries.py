"""Интеграционные тесты на supply_lab после установки ЛР1 и ЛР3.

Отсутствующая база или функция — ошибка окружения, а не skip.
Каждый тест использует отдельную транзакцию с принудительным откатом.
"""

import contextlib
from datetime import timedelta
from decimal import Decimal
import io
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg.pq import TransactionStatus

try:
    from lr6.src import cli, db, queries
except ModuleNotFoundError as error:
    if error.name != "lr6":
        raise
    from src import cli, db, queries


class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.connection = db.connect()
        cls.addClassCleanup(cls.connection.close)
        dependencies = cls.connection.execute("""
            SELECT to_regprocedure('public.fn_delivery_total(bigint)'),
                   to_regprocedure('public.fn_supplier_deliveries(bigint)'),
                   to_regprocedure('public.sp_describe_table(text,jsonb)')
        """).fetchone()
        if any(value is None for value in dependencies):
            raise RuntimeError("Не установлены функции и процедура ЛР3.")
        cls.delivery = cls.connection.execute("""
            SELECT delivery_id, supplier_id, quantity * unit_cost
            FROM public.deliveries ORDER BY delivery_id LIMIT 1
        """).fetchone()
        if cls.delivery is None:
            raise RuntimeError("Для тестов нужны поставки из ЛР1.")
        cls.missing_id = cls.connection.execute(
            "SELECT greatest(max(delivery_id), 0) + 1 FROM public.deliveries"
        ).fetchone()[0]
        cls.start, cls.end = cls.connection.execute(
            "SELECT min(delivered_at)::date, max(delivered_at)::date FROM public.deliveries"
        ).fetchone()
        cls.end += timedelta(days=1)

    def setUp(self) -> None:
        self.enterContext(self.connection.transaction(force_rollback=True))

    def test_01_scalar_count(self) -> None:
        for status in queries.STATUSES:
            with self.subTest(status=status):
                expected = self.connection.execute(
                    "SELECT count(*) FROM public.deliveries WHERE quality_status = %s", (status,)
                ).fetchone()[0]
                self.assertEqual(queries.show_delivery_count_by_status(self.connection, status), expected)

    def test_02_joins_and_limit(self) -> None:
        columns, rows = queries.show_recent_deliveries(self.connection, 7)
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), 7)
        for values in rows:
            row = dict(zip(columns, values))
            delivery = self.connection.execute(
                """
                SELECT supplier_id, product_id, warehouse_id, delivered_at,
                       quantity, quantity * unit_cost
                FROM public.deliveries WHERE delivery_id = %s
            """,
                (row['delivery_id'],),
            ).fetchone()
            self.assertEqual(
                delivery,
                tuple(
                    row[key]
                    for key in ('supplier_id', 'product_id', 'warehouse_id', 'delivered_at', 'quantity', 'total_cost')
                ),
            )
            for table, key in (
                ("suppliers", "supplier_id"),
                ("products", "product_id"),
                ("warehouses", "warehouse_id"),
            ):
                # Идентификаторы SQL взяты из фиксированных констант теста.
                query = psycopg.sql.SQL("SELECT name FROM public.{} WHERE {} = %s").format(
                    psycopg.sql.Identifier(table), psycopg.sql.Identifier(key)
                )
                name = self.connection.execute(query, (row[key],)).fetchone()[0]
                self.assertEqual(row[key.replace('_id', '_name')], name)
        order = [(row[7], row[0]) for row in rows]
        self.assertEqual(order, sorted(order, reverse=True))

    def test_03_ranking_totals_shares_and_running_sum(self) -> None:
        _, rows = queries.show_supplier_cost_rating(self.connection, self.start, self.end)
        self.assertTrue(rows)
        expected = dict(
            self.connection.execute(
                """
            SELECT supplier_id, sum(quantity * unit_cost)
            FROM public.deliveries
            WHERE delivered_at >= %s AND delivered_at < %s
            GROUP BY supplier_id
        """,
                (self.start, self.end),
            ).fetchall()
        )
        self.assertEqual({row[0]: row[2] for row in rows}, expected)
        rank, previous_total, running = 0, None, Decimal(0)
        for _, _, total, actual_rank, _, cumulative in rows:
            if total != previous_total:
                rank += 1
            self.assertEqual(actual_rank, rank)
            if previous_total is not None:
                self.assertGreaterEqual(previous_total, total)
            previous_total = total
            running += total
            self.assertEqual(cumulative, running)
        if running:
            self.assertLess(abs(sum(row[4] for row in rows) - 100), Decimal('0.000001'))
        else:
            self.assertTrue(all(row[4] is None for row in rows))

    def test_03_period_is_half_open_and_empty_is_valid(self) -> None:
        end = self.start + timedelta(days=1)
        _, rows = queries.show_supplier_cost_rating(self.connection, self.start, end)
        expected = self.connection.execute(
            """
            SELECT coalesce(sum(quantity * unit_cost), 0)
            FROM public.deliveries WHERE delivered_at >= %s AND delivered_at < %s
        """,
            (self.start, end),
        ).fetchone()[0]
        self.assertEqual(sum(row[2] for row in rows), expected)
        self.assertEqual(
            queries.show_supplier_cost_rating(self.connection, self.end, self.end + timedelta(days=1))[1], []
        )

    def test_04_column_metadata(self) -> None:
        _, rows = queries.describe_columns(self.connection, "deliveries")
        self.assertTrue({"delivery_id", "batch_number"}.issubset({row[1] for row in rows}))
        self.assertEqual([row[0] for row in rows], list(range(1, len(rows) + 1)))

    def test_05_scalar_function_and_error_recovery(self) -> None:
        self.assertEqual(queries.show_delivery_total(self.connection, self.delivery[0]), self.delivery[2])
        with self.assertRaises(psycopg.Error):
            queries.show_delivery_total(self.connection, self.missing_id)
        self.assertEqual(queries.show_delivery_total(self.connection, self.delivery[0]), self.delivery[2])

    def test_06_table_function(self) -> None:
        columns, rows = queries.show_supplier_deliveries(self.connection, self.delivery[1])
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), 100)
        for values in rows:
            row = dict(zip(columns, values))
            supplier_id = self.connection.execute(
                "SELECT supplier_id FROM public.deliveries WHERE delivery_id = %s", (row['delivery_id'],)
            ).fetchone()[0]
            self.assertEqual(supplier_id, self.delivery[1])
        missing = self.connection.execute("SELECT max(supplier_id) + 1 FROM public.suppliers").fetchone()[0]
        self.assertEqual(queries.show_supplier_deliveries(self.connection, missing)[1], [])

    def test_07_procedure_json(self) -> None:
        metadata = queries.describe_table_with_procedure(self.connection, "deliveries")
        self.assertEqual(metadata['name'], 'deliveries')
        self.assertEqual(metadata['schema'], 'public')
        self.assertIn('delivery_id', {column['name'] for column in metadata['columns']})

    def test_08_system_functions(self) -> None:
        _, rows = queries.show_server_info(self.connection)
        self.assertEqual(rows[0][0], "supply_lab")
        self.assertIn("PostgreSQL", rows[0][3])

    def test_09_idempotent_ddl(self) -> None:
        queries.create_delivery_notes_table(self.connection)
        queries.create_delivery_notes_table(self.connection)
        self.assertIsNotNone(self.connection.execute("SELECT to_regclass('lr6.delivery_notes')").fetchone()[0])
        columns = self.connection.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'lr6' AND table_name = 'delivery_notes'
            ORDER BY ordinal_position
        """).fetchall()
        self.assertEqual(
            [row[0] for row in columns], ['note_id', 'delivery_id', 'note_text', 'created_at', 'created_by']
        )

    def test_10_insert_injection_foreign_key_and_recovery(self) -> None:
        queries.create_delivery_notes_table(self.connection)
        text = "'); DROP TABLE public.deliveries; -- " + str(uuid4())
        _, rows = queries.add_delivery_note(self.connection, self.delivery[0], text)
        note_id, delivery_id, note_text, created_at, created_by = rows[0]
        self.assertGreater(note_id, 0)
        self.assertEqual((delivery_id, note_text), (self.delivery[0], text))
        self.assertIsNotNone(created_at.tzinfo)
        self.assertEqual(created_by, self.connection.execute("SELECT session_user").fetchone()[0])
        self.assertEqual(
            self.connection.execute(
                "SELECT note_text FROM lr6.delivery_notes WHERE note_id = %s", (note_id,)
            ).fetchone()[0],
            text,
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            queries.add_delivery_note(self.connection, self.missing_id, "invalid FK")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.transaction():
                self.connection.execute(
                    "INSERT INTO lr6.delivery_notes(delivery_id, note_text) VALUES (%s, '   ')",
                    (self.delivery[0],),
                )
        queries.add_delivery_note(self.connection, self.delivery[0], "После ошибки")
        self.assertEqual(queries.show_delivery_total(self.connection, self.delivery[0]), self.delivery[2])

    def test_transaction_rollback_removes_changes(self) -> None:
        before = self.connection.execute("SELECT to_regclass('lr6.delivery_notes')").fetchone()[0]
        marker = str(uuid4())
        with self.connection.transaction(force_rollback=True):
            queries.create_delivery_notes_table(self.connection)
            queries.add_delivery_note(self.connection, self.delivery[0], marker)
        after = self.connection.execute("SELECT to_regclass('lr6.delivery_notes')").fetchone()[0]
        self.assertEqual(after, before)
        if after is not None:
            self.assertEqual(
                self.connection.execute(
                    "SELECT count(*) FROM lr6.delivery_notes WHERE note_text = %s", (marker,)
                ).fetchone()[0],
                0,
            )

    def test_autocommit_reads_leave_no_open_transaction(self) -> None:
        with db.connect() as connection:
            for action in (
                lambda: queries.show_server_info(connection),
                lambda: queries.show_delivery_count_by_status(connection, "accepted"),
                lambda: queries.show_delivery_total(connection, self.delivery[0]),
                lambda: queries.describe_table_with_procedure(connection, "deliveries"),
            ):
                action()
                self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            with self.assertRaises(psycopg.Error):
                queries.show_delivery_total(connection, self.missing_id)
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            self.assertEqual(queries.show_server_info(connection)[1][0][0], 'supply_lab')

    def test_all_menu_commands_with_real_database(self) -> None:
        marker = "Проверка меню " + str(uuid4())
        inputs = [
            "1",
            "accepted",
            "2",
            "2",
            "3",
            self.start.isoformat(),
            self.end.isoformat(),
            "4",
            "deliveries",
            "5",
            str(self.delivery[0]),
            "6",
            str(self.delivery[1]),
            "7",
            "deliveries",
            "8",
            "9",
            "10",
            str(self.delivery[0]),
            marker,
            "5",
            str(self.missing_id),
            "8",
            "0",
        ]
        output = io.StringIO()
        with patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(output):
            cli.run_menu(self.connection)
        rendered = output.getvalue()
        self.assertEqual(rendered.count(cli.MENU), 13)
        self.assertEqual(rendered.count("Ошибка PostgreSQL:"), 1)
        self.assertIn("Таблица lr6.delivery_notes готова.", rendered)
        self.assertIn(marker, rendered)
        self.assertIn('"schema": "public"', rendered)
        self.assertEqual(rendered.count("current_database"), 2)
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM lr6.delivery_notes WHERE note_text = %s", (marker,)
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
