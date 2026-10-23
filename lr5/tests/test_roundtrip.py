"""Integration tests for the LR5 JSON Lines export/import round trip."""

import json
import tempfile
import unittest
from pathlib import Path

import psycopg

from lr5.src.db import DELIVERIES_FILE, connection_parameters
from lr5.src.export_deliveries import export_deliveries
from lr5.src.import_deliveries import import_deliveries


TABLES_ARE_EQUAL_SQL = """
SELECT NOT EXISTS (
    SELECT
        delivery_id,
        supplier_id,
        product_id,
        warehouse_id,
        delivered_at,
        quantity,
        unit_cost,
        batch_number,
        quality_status,
        expires_on
    FROM public.deliveries
    EXCEPT
    SELECT
        delivery_id,
        supplier_id,
        product_id,
        warehouse_id,
        delivered_at,
        quantity,
        unit_cost,
        batch_number,
        quality_status,
        expires_on
    FROM lr5.deliveries_imported
) AND NOT EXISTS (
    SELECT
        delivery_id,
        supplier_id,
        product_id,
        warehouse_id,
        delivered_at,
        quantity,
        unit_cost,
        batch_number,
        quality_status,
        expires_on
    FROM lr5.deliveries_imported
    EXCEPT
    SELECT
        delivery_id,
        supplier_id,
        product_id,
        warehouse_id,
        delivered_at,
        quantity,
        unit_cost,
        batch_number,
        quality_status,
        expires_on
    FROM public.deliveries
)
"""


class DeliveryRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.exported_rows = export_deliveries()
        cls.imported_rows = import_deliveries()

    def assert_imported_table_unchanged(self) -> None:
        with psycopg.connect(**connection_parameters()) as connection:
            is_equal = connection.execute(TABLES_ARE_EQUAL_SQL).fetchone()[0]
        self.assertTrue(is_equal)

    def test_export_is_valid_json_lines(self) -> None:
        records = []
        with DELIVERIES_FILE.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                with self.subTest(line_number=line_number):
                    payload = json.loads(line)
                    self.assertIsInstance(payload, dict)
                    records.append(payload)

        self.assertEqual(len(records), self.exported_rows)
        self.assertEqual(len(records), self.imported_rows)

        with psycopg.connect(**connection_parameters()) as connection:
            source_rows = connection.execute(
                "SELECT count(*) FROM public.deliveries"
            ).fetchone()[0]
        self.assertEqual(len(records), source_rows)

    def test_round_trip_preserves_every_delivery(self) -> None:
        self.assert_imported_table_unchanged()

    def test_malformed_json_rolls_back_the_import(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lr5-malformed-") as directory:
            invalid_file = Path(directory) / "deliveries.jsonl"
            invalid_file.write_text('{"delivery_id": 1\n', encoding="utf-8")

            with self.assertRaises((psycopg.Error, ValueError)):
                import_deliveries(invalid_file)

        self.assert_imported_table_unchanged()

    def test_missing_key_rolls_back_the_import(self) -> None:
        first_record = json.loads(
            DELIVERIES_FILE.read_text(encoding="utf-8").splitlines()[0]
        )
        first_record.pop("expires_on")

        with tempfile.TemporaryDirectory(prefix="lr5-missing-key-") as directory:
            invalid_file = Path(directory) / "deliveries.jsonl"
            invalid_file.write_text(
                json.dumps(first_record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises((psycopg.Error, ValueError)):
                import_deliveries(invalid_file)

        self.assert_imported_table_unchanged()


if __name__ == "__main__":
    unittest.main()
