import importlib
import json
import os
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from psycopg import Cursor
from sqlalchemy import Connection, event, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import ExecutionContext
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.schema import MetaData

try:
    from lr7.src import models
    from lr7.src.db import make_engine, make_session_factory
    from lr7.src.json_queries import export_json, read_json
    from lr7.src.repository import Repository, products_statement
except ModuleNotFoundError as error:
    if error.name != "lr7":
        raise
    from src import models
    from src.db import make_engine, make_session_factory
    from src.json_queries import export_json, read_json
    from src.repository import Repository, products_statement


class MappingTests(unittest.TestCase):
    def test_import_has_no_ddl_or_connection(self) -> None:
        # Изолированное исполнение файла не изменяет registry рабочих моделей.
        spec = importlib.util.spec_from_file_location(
            "lr7_model_import_test", models.__file__
        )
        module = importlib.util.module_from_spec(spec)
        with (
            patch.object(
                MetaData, "create_all", side_effect=AssertionError("Unexpected DDL")
            ),
            patch(
                "sqlalchemy.create_engine",
                side_effect=AssertionError("Unexpected engine"),
            ),
        ):
            spec.loader.exec_module(module)
        self.assertTrue(issubclass(module.Base, DeclarativeBase))
        self.assertEqual(
            set(module.Base.metadata.tables),
            {
                "public.suppliers",
                "public.products",
                "public.warehouses",
                "public.deliveries",
                "lr7.delivery_tags",
            },
        )

    def test_product_statement_binds_parameters(self) -> None:
        category = "category'; DROP TABLE public.products; --"
        compiled = products_statement(category, Decimal("100.25"), 3).compile(
            dialect=postgresql.dialect()
        )
        self.assertNotIn(category, str(compiled))
        self.assertIn(category, compiled.params.values())
        self.assertIn(Decimal("100.25"), compiled.params.values())
        self.assertIn(3, compiled.params.values())
        self.assertIn(
            "ORDER BY public.products.unit_price DESC, public.products.sku",
            str(compiled),
        )
        with self.assertRaises(ValueError):
            products_statement("x", Decimal(1), -1)

    def test_session_configuration(self) -> None:
        with make_session_factory(None)() as session:
            self.assertFalse(session.autoflush)
            self.assertFalse(session.expire_on_commit)
            self.assertFalse(session.autobegin)


@unittest.skipUnless(
    os.environ.get("LR7_INTEGRATION") == "1", "set LR7_INTEGRATION=1 to test PostgreSQL"
)
class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = make_engine()
        cls.addClassCleanup(cls.engine.dispose)

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.addCleanup(self.connection.close)
        self.transaction = self.connection.begin()
        self.addCleanup(
            lambda: self.transaction.rollback() if self.transaction.is_active else None
        )
        self.sessions = make_session_factory(self.connection)
        self.repository = Repository(self.sessions)
        with self.sessions() as session, session.begin():
            self.delivery = session.scalars(
                select(models.Delivery).order_by(models.Delivery.delivery_id).limit(1)
            ).one()
            self.product = session.get(models.Product, self.delivery.product_id)
            self.supplier = session.get(models.Supplier, self.delivery.supplier_id)
            self.warehouse = session.get(models.Warehouse, self.delivery.warehouse_id)

    def test_models_match_existing_columns_and_keys(self) -> None:
        inspector = inspect(self.connection)
        for model in (
            models.Supplier,
            models.Product,
            models.Warehouse,
            models.Delivery,
            models.DeliveryTag,
        ):
            with self.subTest(table=model.__tablename__):
                table = model.__table__
                columns = {
                    column["name"]: column
                    for column in inspector.get_columns(table.name, schema=table.schema)
                }
                self.assertEqual(set(columns), set(table.columns.keys()))
                for column in table.columns:
                    actual = columns[column.name]
                    self.assertEqual(column.nullable, actual["nullable"])
                    self.assertEqual(
                        column.type.compile(dialect=self.engine.dialect),
                        actual["type"].compile(dialect=self.engine.dialect),
                    )
                primary = inspector.get_pk_constraint(table.name, schema=table.schema)
                self.assertEqual(
                    primary["constrained_columns"],
                    list(table.primary_key.columns.keys()),
                )
                actual_foreign = {
                    (
                        tuple(key["constrained_columns"]),
                        key["referred_schema"] or inspector.default_schema_name,
                        key["referred_table"],
                        tuple(key["referred_columns"]),
                    )
                    for key in inspector.get_foreign_keys(
                        table.name, schema=table.schema
                    )
                }
                expected_foreign = {
                    (
                        (key.parent.name,),
                        key.column.table.schema,
                        key.column.table.name,
                        (key.column.name,),
                    )
                    for key in table.foreign_keys
                }
                self.assertEqual(actual_foreign, expected_foreign)

    def test_select_products_result(self) -> None:
        result = self.repository.select_products(
            self.product.category, self.product.unit_price, 3
        )
        with self.sessions() as session, session.begin():
            products = list(session.scalars(select(models.Product)))
        expected = sorted(
            [
                p
                for p in products
                if p.category == self.product.category
                and p.unit_price >= self.product.unit_price
            ],
            key=lambda p: (-p.unit_price, p.sku),
        )[:3]
        self.assertEqual(
            [p.product_id for p in result], [p.product_id for p in expected]
        )
        self.assertTrue(result)
        self.assertEqual(
            self.repository.select_products(self.product.category, Decimal(0), 0), []
        )
        self.assertEqual(
            self.repository.select_products("'; DROP TABLE x; --", Decimal(0), 3), []
        )

    def test_join_fields_and_half_open_dates(self) -> None:
        start = self.delivery.delivered_at
        rows = self.repository.select_delivery_details(
            start, start + timedelta(microseconds=1)
        )
        row = next(
            row for row in rows if row["delivery_id"] == self.delivery.delivery_id
        )
        self.assertEqual(row["supplier_name"], self.supplier.name)
        self.assertEqual(row["tax_id"], self.supplier.tax_id)
        self.assertEqual(row["product_name"], self.product.name)
        self.assertEqual(row["sku"], self.product.sku)
        self.assertEqual(row["warehouse_code"], self.warehouse.code)
        self.assertEqual(row["warehouse_city"], self.warehouse.city)
        self.assertEqual(
            row["total_cost"], self.delivery.quantity * self.delivery.unit_cost
        )
        preceding = self.repository.select_delivery_details(
            start - timedelta(microseconds=1), start
        )
        self.assertNotIn(
            self.delivery.delivery_id, [row["delivery_id"] for row in preceding]
        )
        self.assertEqual(self.repository.select_delivery_details(start, start), [])
        with self.assertRaises(ValueError):
            self.repository.select_delivery_details(start + timedelta(days=1), start)

    def test_insert_update_delete(self) -> None:
        tag = f"test-{uuid4().hex}"
        tag_id = self.repository.insert_delivery_tag(self.delivery.delivery_id, tag)
        with self.sessions() as session, session.begin():
            row = session.get(models.DeliveryTag, tag_id)
            self.assertEqual(row.tag, tag)
            self.assertIsNotNone(row.created_at.tzinfo)
        renamed = f"edit-{uuid4().hex}"
        self.assertEqual(self.repository.rename_delivery_tag(tag_id, renamed), tag_id)
        with self.sessions() as session, session.begin():
            self.assertEqual(session.get(models.DeliveryTag, tag_id).tag, renamed)
        self.assertEqual(self.repository.delete_delivery_tag(tag_id), tag_id)
        with self.sessions() as session, session.begin():
            self.assertIsNone(session.get(models.DeliveryTag, tag_id))
        with self.assertRaises(NoResultFound):
            self.repository.rename_delivery_tag(tag_id, "missing")
        with self.assertRaises(NoResultFound):
            self.repository.delete_delivery_tag(tag_id)

    def test_duplicate_rolls_back_and_session_remains_usable(self) -> None:
        tag = f"test-{uuid4().hex}"
        tag_id = self.repository.insert_delivery_tag(self.delivery.delivery_id, tag)
        with self.assertRaises(IntegrityError):
            self.repository.insert_delivery_tag(self.delivery.delivery_id, tag)
        with self.sessions() as session, session.begin():
            rows = session.scalars(
                select(models.DeliveryTag).where(
                    models.DeliveryTag.delivery_id == self.delivery.delivery_id,
                    models.DeliveryTag.tag == tag,
                )
            ).all()
            self.assertEqual([row.tag_id for row in rows], [tag_id])
        second = self.repository.insert_delivery_tag(
            self.delivery.delivery_id, f"test-{uuid4().hex}"
        )
        with self.assertRaises(IntegrityError):
            self.repository.rename_delivery_tag(second, tag)
        self.repository.delete_delivery_tag(second)

    def test_database_rejects_empty_tag_and_unknown_delivery(self) -> None:
        with self.assertRaises(IntegrityError):
            self.repository.insert_delivery_tag(self.delivery.delivery_id, "   ")
        with self.assertRaises(IntegrityError):
            self.repository.insert_delivery_tag(-1, "missing-delivery")

    def test_external_rollback_removes_committed_session_insert(self) -> None:
        tag_id = self.repository.insert_delivery_tag(
            self.delivery.delivery_id, f"test-{uuid4().hex}"
        )
        self.transaction.rollback()
        with self.sessions() as session, session.begin():
            self.assertIsNone(session.get(models.DeliveryTag, tag_id))

    def capture_statements(self) -> list[str]:
        statements = []

        def capture(
            connection: Connection,
            cursor: Cursor,
            statement: str,
            parameters: object,
            context: ExecutionContext,
            executemany: bool,
        ) -> None:
            if not statement.startswith(
                ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")
            ):
                statements.append(statement)

        event.listen(self.connection, "before_cursor_execute", capture)
        self.addCleanup(event.remove, self.connection, "before_cursor_execute", capture)
        return statements

    def test_procedure_is_only_application_statement(self) -> None:
        statements = self.capture_statements()
        result = self.repository.describe_table_via_procedure("deliveries")
        self.assertEqual(result["schema"], "public")
        self.assertEqual(result["name"], "deliveries")
        self.assertIn("delivery_id", [column["name"] for column in result["columns"]])
        self.assertTrue(result["constraints"])
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CALL public.sp_describe_table("))
        self.assertNotIn("'deliveries'", statements[0])

    def test_json_export_uses_one_joined_select(self) -> None:
        statements = self.capture_statements()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deliveries.json"
            document = export_json(self.sessions, path)
            self.assertEqual(len(statements), 1)
            self.assertTrue(statements[0].startswith("SELECT"))
            self.assertEqual(statements[0].count(" JOIN "), 3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), document)
            first = next(
                row
                for row in document["deliveries"]
                if row["delivery_id"] == self.delivery.delivery_id
            )
            self.assertEqual(first["supplier"]["tax_id"], self.supplier.tax_id)
            self.assertEqual(first["unit_cost"], str(self.delivery.unit_cost))
            self.assertEqual(first["tags"], [])
            self.assertTrue(read_json(path, self.delivery.quality_status))

    def test_loaded_collections_are_detached_and_readable(self) -> None:
        data = self.repository.load_collections()
        for collection in data.values():
            self.assertTrue(collection)
            self.assertTrue(inspect(collection[0]).detached)
        self.assertEqual(data["deliveries"][0].delivery_id, self.delivery.delivery_id)
