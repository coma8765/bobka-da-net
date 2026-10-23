"""Stream public.deliveries to an atomically replaced JSON Lines file."""

import os
import tempfile
from pathlib import Path

import psycopg

try:
    from .db import DATA_DIR, DELIVERIES_FILE, connection_parameters
except ImportError:
    from db import DATA_DIR, DELIVERIES_FILE, connection_parameters


EXPORT_SQL = """
COPY (
    SELECT to_jsonb(d)::text
    FROM public.deliveries AS d
    ORDER BY d.delivery_id
) TO STDOUT
"""


def export_deliveries(destination: Path = DELIVERIES_FILE) -> int:
    """Export deliveries as UTF-8 JSONL and return the number of rows."""

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    exported_rows = 0

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as output:
            temporary_path = Path(output.name)

            with psycopg.connect(**connection_parameters()) as connection:
                with connection.cursor() as cursor:
                    with cursor.copy(EXPORT_SQL) as copy:
                        copy.set_types(["text"])
                        for (payload,) in copy.rows():
                            output.write(payload)
                            output.write("\n")
                            exported_rows += 1

            output.flush()
            os.fsync(output.fileno())

        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    return exported_rows


def main() -> None:
    exported_rows = export_deliveries()
    print(f"Exported {exported_rows} deliveries to {DELIVERIES_FILE}")


if __name__ == "__main__":
    main()
