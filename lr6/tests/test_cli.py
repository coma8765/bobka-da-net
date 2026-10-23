import contextlib
from datetime import date
import io
import unittest
from unittest.mock import patch

import psycopg

try:
    from lr6.src import cli, db, queries
except ModuleNotFoundError as error:
    if error.name != "lr6":
        raise
    from src import cli, db, queries


class InputTests(unittest.TestCase):
    def test_readers_retry_invalid_input(self) -> None:
        cases = [
            (lambda: cli.read_int("", maximum=100), ["text", "0", "101", "7"], 7),
            (lambda: cli.read_date(""), ["2025-02-29", "2024-02-29"], date(2024, 2, 29)),
            (lambda: cli.read_choice("", {"0", "1"}), ["2", " 1 "], "1"),
            (lambda: cli.read_non_empty_text(""), [" \t", " note "], "note"),
        ]
        for reader, inputs, expected in cases:
            with self.subTest(inputs=inputs), patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(
                io.StringIO()
            ):
                self.assertEqual(reader(), expected)

    def test_table_prints_headers_null_and_empty_result(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.print_table((["value"], [(None,), ("a\nb",)]))
            cli.print_table((["value"], []))
        self.assertIn("value", output.getvalue())
        self.assertIn("NULL", output.getvalue())
        self.assertIn("a\\nb", output.getvalue())
        self.assertIn("Строки не найдены", output.getvalue())

    def test_eof_and_interrupt_exit_cleanly(self) -> None:
        for exception in (EOFError, KeyboardInterrupt):
            with self.subTest(exception=exception), patch.object(db, "connect"), patch(
                "builtins.input", side_effect=exception
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(), 0)

    def test_menu_recovers_after_query_errors(self) -> None:
        errors = [
            ("5", psycopg.errors.RaiseException("unknown id"), "unknown id"),
            ("5", psycopg.errors.UndefinedFunction("missing"), "ЛР3"),
            ("10", psycopg.errors.UndefinedTable("missing"), "пункт 9"),
            ("10", psycopg.errors.ForeignKeyViolation("invalid"), "Нарушение ограничений"),
            ("3", ValueError("invalid period"), "invalid period"),
        ]
        for command, error, message in errors:
            output = io.StringIO()
            with self.subTest(error=error), patch("builtins.input", side_effect=[command, "8", "0"]), patch.object(
                cli, "execute_command", side_effect=[error, None]
            ) as execute, contextlib.redirect_stdout(output):
                cli.run_menu(object())
                self.assertEqual(execute.call_count, 2)
                self.assertIn(message, output.getvalue())

    def test_startup_error_returns_failure(self) -> None:
        with patch.object(
            db, "connect", side_effect=psycopg.OperationalError("unavailable")
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(), 1)
        self.assertIn("Не удалось открыть базу", output.getvalue())

    def test_validation_before_sql(self) -> None:
        # None вместо соединения доказывает, что неверный ввод не дошёл до БД.
        cases = [
            (queries.show_delivery_count_by_status, ("accepted' OR 1=1 --",)),
            (queries.show_recent_deliveries, (0,)),
            (queries.show_recent_deliveries, (101,)),
            (queries.show_recent_deliveries, (True,)),
            (queries.describe_columns, ("deliveries; DROP SCHEMA public CASCADE",)),
            (queries.describe_table_with_procedure, ("pg_proc",)),
            (queries.show_delivery_total, (-1,)),
            (queries.show_supplier_deliveries, ("1 OR 1=1",)),
            (queries.add_delivery_note, (1, " \t\n")),
            (queries.show_supplier_cost_rating, (date(2025, 1, 1), date(2025, 1, 1))),
            (queries.show_supplier_cost_rating, (date(2025, 1, 2), date(2025, 1, 1))),
        ]
        for function, arguments in cases:
            with self.subTest(function=function.__name__, arguments=arguments), self.assertRaises(ValueError):
                function(None, *arguments)


if __name__ == "__main__":
    unittest.main()
