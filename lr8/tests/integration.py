"""End-to-end checks against a running lr8 NiFi and lr1-postgres.

Creates uniquely identified test events in lr8.delivery_events and leaves the
receipts/archive as evidence. Does not delete data or change the NiFi flow.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from generator import generate_file  # noqa: E402

RUNTIME = ROOT / "runtime"


def database_count(file_id):
    # file_id is always generated locally as UUID, never taken from an input file.
    file_id = str(uuid.UUID(file_id))
    sql = f"SELECT count(*) FROM lr8.delivery_events WHERE source_file_id = '{file_id}'::uuid;"
    run = subprocess.run(
        [
            "podman",
            "exec",
            os.environ.get("PG_CONTAINER", "lr1-postgres"),
            "psql",
            "-X",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "supply_lab",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(run.stdout.strip())


def wait_for_receipt(name, loaded):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        matches = (
            list((RUNTIME / "receipts").glob(name + ".loaded.json"))
            if loaded
            else list((RUNTIME / "rejected").glob(name + ".*.rejected.json.error.json"))
        )
        if matches:
            try:
                return matches[0], json.loads(matches[0].read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(1)
    raise AssertionError("No receipt: " + name)


def publish(name, raw):
    temporary = RUNTIME / "outbox" / (str(uuid.uuid4()) + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, RUNTIME / "inbox" / name)


def main():
    cases = []
    mutations = {
        "missing field": lambda rows: rows[-1].pop("quantity"),
        "invalid quantity": lambda rows: rows[-1].update(quantity=0),
        "invalid price": lambda rows: rows[-1].update(unit_cost=-1),
        "invalid status": lambda rows: rows[-1].update(quality_status="unknown"),
        "mismatched source": lambda rows: rows[-1].update(
            source_file_id=str(uuid.uuid4())
        ),
        "duplicate event": lambda rows: rows[-1].update(event_id=rows[0]["event_id"]),
        "string quantity": lambda rows: rows[-1].update(quantity="3"),
        "invalid date": lambda rows: rows[-1].update(expires_on="2026-02-30"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        for label in [
            "valid",
            "valid 20 records",
            "invalid filename",
            "malformed JSON",
            "empty array",
            "object root",
            *mutations,
        ]:
            path, count = generate_file(
                Path(tmp), 20 if label == "valid 20 records" else 2
            )
            rows = json.loads(path.read_bytes())
            rows[0]["expires_on"] = "2027-09-28"
            rows[1]["expires_on"] = None
            file_id = rows[0]["source_file_id"]
            name = path.name
            if label in mutations:
                mutations[label](rows)
            raw = json.dumps(rows, indent=2).encode() + b"\n"
            if label == "invalid filename":
                name = file_id + ".json"
            elif label == "malformed JSON":
                raw = b"{broken json\n"
            elif label == "empty array":
                raw = b"[]\n"
            elif label == "object root":
                raw = json.dumps(rows[0]).encode()
            publish(name, raw)
            cases.append(
                (label, file_id, name, raw, count if label.startswith("valid") else 0)
            )
        for label, file_id, name, raw, expected in cases:
            receipt_path, receipt = wait_for_receipt(name, expected > 0)
            assert database_count(file_id) == expected, label
            assert receipt["load.status"] == ("loaded" if expected else "rejected"), (
                receipt
            )
            if expected:
                originals = list((RUNTIME / "archive").glob("*/" + name))
                assert len(originals) == 1 and originals[0].read_bytes() == raw, (
                    "archive differs"
                )
                assert int(receipt["record_count"]) == expected, receipt
            else:
                original = Path(str(receipt_path).removesuffix(".error.json"))
                assert original.read_bytes() == raw, "rejected original differs"
            print("PASS:", label, flush=True)
        _, file_id, name, raw, expected = cases[0]
        publish(name, raw)
        _, receipt = wait_for_receipt(name, False)
        assert database_count(file_id) == expected
        assert receipt["error.stage"] == "database", receipt
        for field in (
            "supplier_tax_id",
            "product_sku",
            "warehouse_code",
            "batch_number",
        ):
            assert json.loads(raw)[0][field] not in receipt["error.reason"], (
                "record data leaked into receipt"
            )
        print("PASS: duplicate delivery rejected without extra rows", flush=True)
        # A new first row followed by an existing primary key must roll back both.
        path, _ = generate_file(Path(tmp), 2)
        mixed = json.loads(path.read_bytes())
        mixed[1]["event_id"] = json.loads(cases[0][3])[0]["event_id"]
        publish(path.name, json.dumps(mixed).encode())
        _, receipt = wait_for_receipt(path.name, False)
        assert receipt["error.stage"] == "database", receipt
        assert database_count(mixed[0]["source_file_id"]) == 0
        print("PASS: database conflict in second row rolls back first row", flush=True)
        print("All 16 NiFi integration scenarios passed.")


if __name__ == "__main__":
    main()
