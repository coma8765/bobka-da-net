"""Generate new delivery events, publishing each file atomically."""

import argparse
import datetime as dt
import json
import os
import random
import time
import uuid
from pathlib import Path

from validation import STATUSES, validate_records

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTERVAL = 300


def generate_file(runtime=ROOT / "runtime", count=None):
    runtime = Path(runtime)
    inbox, outbox = runtime / "inbox", runtime / "outbox"
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    if inbox.stat().st_dev != outbox.stat().st_dev:
        raise ValueError("inbox and outbox must be on the same filesystem")
    if count is None:
        count = random.randint(1, 20)
    if type(count) is not int or not 1 <= count <= 20:
        raise ValueError("count must be between 1 and 20")
    file_id = str(uuid.uuid4())
    now = dt.datetime.now(dt.timezone.utc)
    filename = f"{file_id}__delivery_events__{now:%Y%m%dT%H%M%SZ}.json"
    records = []
    for _ in range(count):
        event_id = str(uuid.uuid4())
        records.append(
            {
                "event_id": event_id,
                "source_file_id": file_id,
                # Natural key formats and ranges match lr1/generator/generate_data.py.
                "supplier_tax_id": str(7700000000 + random.randint(1, 1000)),
                "product_sku": f"SKU-{random.randint(1, 1000):06d}",
                "warehouse_code": f"WH-{random.randint(1, 1000):05d}",
                "delivered_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "quantity": random.randint(1, 1000),
                "unit_cost": random.randint(1, 10000000) / 100,
                "batch_number": f"ETL-{uuid.UUID(event_id).hex}",
                "quality_status": random.choice(STATUSES),
                "expires_on": (now.date() + dt.timedelta(days=365)).isoformat()
                if random.choice((True, False))
                else None,
            }
        )
    validate_records(records, filename)
    temporary = outbox / f"{file_id}.tmp"
    stream = temporary.open("x", encoding="utf-8", newline="\n")
    try:
        with stream:
            json.dump(records, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        destination = inbox / filename
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination, count


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="publish one file")
    mode.add_argument(
        "--watch", action="store_true", help="publish periodically (default)"
    )
    result.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    result.add_argument("--count", type=int, choices=range(1, 21))
    result.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.interval <= 0:
        cli.error("--interval must be positive")
    try:
        while True:
            started = time.monotonic()
            path, count = generate_file(args.runtime, args.count)
            print(f"created {path.name}: {count} records", flush=True)
            if args.once:
                return
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
