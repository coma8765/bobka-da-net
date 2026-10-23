import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import generator  # noqa: E402
from validation import decode_json, validate_records  # noqa: E402


class GeneratorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)
        self.path, self.count = generator.generate_file(self.runtime, 20)
        self.raw = self.path.read_bytes()
        self.rows = json.loads(self.raw)

    def test_unique_files_and_events(self):
        other, count = generator.generate_file(self.runtime, 20)
        second = json.loads(other.read_bytes())
        self.assertNotEqual(self.path, other)
        self.assertEqual((self.count, count), (20, 20))
        validate_records(decode_json(self.raw), self.path.name)
        for key in ("event_id", "batch_number"):
            self.assertEqual(len({r[key] for r in self.rows + second}), 40)
        self.assertEqual(len(list((self.runtime / "inbox").iterdir())), 2)
        self.assertEqual(list((self.runtime / "outbox").iterdir()), [])

    def test_atomic_publication(self):
        replace = generator.os.replace
        observed = []

        def inspect(source, dest):
            self.assertFalse(dest.exists())
            validate_records(decode_json(source.read_bytes()), dest.name)
            observed.append(dest)
            replace(source, dest)

        with patch.object(generator.os, "replace", side_effect=inspect):
            path, _ = generator.generate_file(self.runtime)
        self.assertEqual(observed, [path])

    def test_failed_publish_does_not_leave_partial_files(self):
        with patch.object(generator.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                generator.generate_file(self.runtime)
        self.assertEqual(list((self.runtime / "outbox").iterdir()), [])
        self.assertEqual(len(list((self.runtime / "inbox").iterdir())), 1)

    def test_existing_temporary_file_is_not_removed(self):
        file_id = self.rows[0]["source_file_id"]
        temporary = self.runtime / "outbox" / f"{file_id}.tmp"
        temporary.write_bytes(b"another publisher")
        with patch.object(
            generator.uuid, "uuid4", return_value=generator.uuid.UUID(file_id)
        ):
            with self.assertRaises(FileExistsError):
                generator.generate_file(self.runtime, 1)
        self.assertEqual(temporary.read_bytes(), b"another publisher")

    def test_schedule_default_and_two_cycles(self):
        self.assertEqual(generator.parser().parse_args([]).interval, 300)
        with patch.object(
            generator, "generate_file", return_value=(self.path, 20)
        ) as emit:
            with patch.object(generator.time, "monotonic", return_value=0):
                with patch.object(
                    generator.time, "sleep", side_effect=[None, KeyboardInterrupt]
                ) as sleep:
                    generator.main(["--watch", "--runtime", self.tmp.name])
        self.assertEqual(emit.call_count, 2)
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [300, 300])

    def test_natural_keys_exist_in_lr1_fixtures(self):
        for filename, column, key in [
            ("suppliers.csv", "tax_id", "supplier_tax_id"),
            ("products.csv", "sku", "product_sku"),
            ("warehouses.csv", "code", "warehouse_code"),
        ]:
            with (ROOT.parent / "lr1/data" / filename).open() as stream:
                known = {row[column] for row in csv.DictReader(stream)}
            self.assertTrue(all(row[key] in known for row in self.rows))

    def test_cli_once(self):
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src/generator.py"),
                "--once",
                "--count",
                "1",
                "--runtime",
                self.tmp.name,
            ],
            capture_output=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(list((self.runtime / "inbox").iterdir())), 2)

    def test_invalid_fields_reject_whole_file(self):
        cases = [
            ("quantity", 0),
            ("quantity", True),
            ("quantity", 1.5),
            ("quantity", 2147483648),
            ("unit_cost", 0),
            ("unit_cost", "2"),
            ("unit_cost", 0.001),
            ("unit_cost", float("nan")),
            ("quality_status", "unknown"),
            ("source_file_id", self.rows[0]["event_id"]),
            ("supplier_tax_id", " "),
            ("warehouse_code", "a" * 17),
            ("event_id", "bad"),
            ("delivered_at", "2026-02-30T00:00:00Z"),
            ("delivered_at", "2026-01-01"),
            ("expires_on", "2026-02-30"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                rows = copy.deepcopy(self.rows)
                rows[-1][key] = value
                with self.assertRaises(ValueError):
                    validate_records(rows, self.path.name)

    def test_invalid_structure(self):
        missing = copy.deepcopy(self.rows)
        del missing[-1]["quantity"]
        extra = copy.deepcopy(self.rows)
        extra[-1]["unknown"] = 1
        for rows in (
            [],
            self.rows[0],
            [None],
            self.rows * 2,
            [self.rows[0], self.rows[0]],
            missing,
            extra,
        ):
            with self.subTest(rows=repr(rows)[:80]):
                with self.assertRaises(ValueError):
                    validate_records(rows, self.path.name)
        for name in (
            "bad.json",
            self.path.name.split("__")[0] + "__delivery_events__20260230T000000Z.json",
        ):
            with self.assertRaises(ValueError):
                validate_records(self.rows, name)

    def test_json_rejects_duplicate_keys_nan_and_malformed(self):
        for raw in (
            b"{",
            b'[{"quantity":1,"quantity":2}]',
            b"[NaN]",
            b"[Infinity]",
            b"\xff",
        ):
            with self.assertRaises((ValueError, UnicodeError)):
                decode_json(raw)

    def test_nifi_validator_preserves_bytes(self):
        command = [sys.executable, str(ROOT / "src/validate_file.py"), self.path.name]
        run = subprocess.run(command, input=self.raw, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, self.raw)
        bad = copy.deepcopy(self.rows)
        bad[-1]["quantity"] = 0
        run = subprocess.run(
            command, input=json.dumps(bad).encode(), capture_output=True
        )
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.stdout, b"")
        self.assertIn(b"quantity", run.stderr)


if __name__ == "__main__":
    unittest.main()
