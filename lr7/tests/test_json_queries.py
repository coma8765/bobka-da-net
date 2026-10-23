import copy
import json
import tempfile
import unittest
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    from lr7.src import json_queries as queries
    from lr7.src.models import QualityStatus
except ModuleNotFoundError as error:
    if error.name != "lr7":
        raise
    from src import json_queries as queries
    from src.models import QualityStatus


def delivery(delivery_id: int = 1, status: str = "accepted") -> dict[str, Any]:
    return {
        "delivery_id": delivery_id,
        "supplier": {"tax_id": "770000000001", "name": "Поставщик"},
        "product": {"sku": "SKU-000001", "name": "Товар"},
        "warehouse": {"code": "WH-0001", "city": "Москва"},
        "quantity": 25,
        "unit_cost": "110.50",
        "quality_status": status,
        "tags": [],
    }


class JsonQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "deliveries.json"
        self.document = {
            "schema_version": 1,
            "generated_at": "2026-09-12T12:00:00Z",
            "deliveries": [delivery(3), delivery(1), delivery(2, "rejected")],
        }
        self.path.write_text(
            json.dumps(self.document, ensure_ascii=False), encoding="utf-8"
        )

    def assert_preserved(
        self,
        operation: Callable[[], object],
        error: type[Exception] = ValueError,
    ) -> None:
        original = self.path.read_bytes()
        with self.assertRaises(error):
            operation()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_read_projection_order_and_decimal(self) -> None:
        rows = queries.read_json(self.path, QualityStatus.ACCEPTED)
        self.assertEqual([row["delivery_id"] for row in rows], [1, 3])
        self.assertEqual(rows[0]["total_cost"], Decimal("2762.50"))
        self.assertEqual(rows[0]["supplier_name"], "Поставщик")
        self.assertEqual(queries.read_json(self.path, "inspection"), [])

    def test_update_exactly_one_and_utf8(self) -> None:
        queries.update_json(self.path, 1, "inspection")
        expected = copy.deepcopy(self.document)
        expected["deliveries"][1]["quality_status"] = "inspection"
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), expected)
        self.assertIn("Поставщик", self.path.read_text(encoding="utf-8"))
        self.assertTrue(self.path.read_bytes().endswith(b"\n"))

    def test_append(self) -> None:
        extra = delivery(4)
        original = copy.deepcopy(extra)
        queries.append_json(self.path, extra)
        result = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result["deliveries"], self.document["deliveries"] + [extra])
        self.assertEqual(extra, original)

    def test_unknown_id_invalid_status_and_duplicate(self) -> None:
        for operation in (
            lambda: queries.update_json(self.path, 999, "accepted"),
            lambda: queries.update_json(self.path, 1, "unknown"),
            lambda: queries.update_json(self.path, True, "accepted"),
            lambda: queries.read_json(self.path, "unknown"),
            lambda: queries.append_json(self.path, delivery(1)),
            lambda: queries.append_json(self.path, delivery(4, "unknown")),
        ):
            with self.subTest(operation=operation):
                self.assert_preserved(operation)

    def test_required_fields(self) -> None:
        for key in delivery():
            with self.subTest(field=key):
                row = delivery(4)
                del row[key]
                self.assert_preserved(
                    lambda row=row: queries.append_json(self.path, row)
                )

    def test_invalid_field_types(self) -> None:
        for key, value in (
            ("delivery_id", True),
            ("delivery_id", 0),
            ("quantity", 0),
            ("quantity", "2"),
            ("unit_cost", 110.50),
            ("unit_cost", "NaN"),
            ("unit_cost", "Infinity"),
            ("unit_cost", "-1"),
            ("unit_cost", "no"),
            ("supplier", {}),
            ("product", {"sku": "X"}),
            ("warehouse", None),
            ("tags", "tag"),
            ("tags", [None]),
        ):
            with self.subTest(field=key, value=value):
                row = delivery(4)
                row[key] = value
                self.assert_preserved(
                    lambda row=row: queries.append_json(self.path, row)
                )

    def test_corrupt_json_unchanged_for_all_operations(self) -> None:
        self.path.write_bytes(b'{"deliveries": [')
        for operation in (
            lambda: queries.read_json(self.path, "accepted"),
            lambda: queries.update_json(self.path, 1, "inspection"),
            lambda: queries.append_json(self.path, delivery(4)),
        ):
            self.assert_preserved(operation)

    def test_invalid_document_and_duplicate_existing_id(self) -> None:
        documents = [
            [],
            {**self.document, "schema_version": 2},
            {**self.document, "generated_at": "yesterday"},
            {**self.document, "deliveries": [delivery(1), delivery(1)]},
        ]
        for document in documents:
            with self.subTest(document=document):
                self.path.write_text(json.dumps(document), encoding="utf-8")
                self.assert_preserved(
                    lambda: queries.update_json(self.path, 1, "inspection")
                )

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self) -> None:
        with patch.object(queries.os, "replace", side_effect=OSError("replace failed")):
            self.assert_preserved(
                lambda: queries.update_json(self.path, 1, "inspection"), OSError
            )

    def test_serialization_failure_preserves_original_and_cleans_temp(self) -> None:
        row = delivery(4)
        row["unsupported_extra"] = object()
        self.assert_preserved(lambda: queries.append_json(self.path, row), TypeError)

    def test_explicit_serializers(self) -> None:
        self.assertEqual(queries.serialize_decimal(Decimal("110.50")), "110.50")
        self.assertEqual(queries.serialize_date(date(2026, 9, 12)), "2026-09-12")
        self.assertEqual(
            queries.serialize_date(
                datetime(2026, 9, 12, 15, tzinfo=timezone(timedelta(hours=3)))
            ),
            "2026-09-12T12:00:00Z",
        )
        self.assertEqual(queries.serialize_status(QualityStatus.REJECTED), "rejected")
        with self.assertRaises(TypeError):
            json.dumps(object(), default=queries.json_default)
