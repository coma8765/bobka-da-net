"""Create and fill the local PostgreSQL database using Psycopg."""

import os
import re
from pathlib import Path

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parent.parent
DATABASE = "supply_lab"
SCRIPTS = (
    ROOT / "queries/01_create_database_and_tables.sql",
    ROOT / "queries/02_add_constraints.sql",
    ROOT / "queries/03_bulk_load.sql",
)
COPY_PATTERN = re.compile(
    r"^\\copy\s+(\w+)\s+\(([^)]*)\)\s+FROM\s+'([^']+)'\s+WITH\s+\((.+)\)$"
)


def connection_parameters(database: str) -> dict[str, object]:
    return {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "55432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", "postgres"),
        "dbname": database,
    }


def create_database() -> None:
    with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if not exists:
            connection.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(
                    sql.Identifier(DATABASE)
                )
            )


def copy_csv(cursor: psycopg.Cursor[object], command: str) -> None:
    match = COPY_PATTERN.fullmatch(command)
    if not match:
        raise ValueError(f"Unsupported copy command: {command}")

    table, column_list, relative_path, options = match.groups()
    columns = [sql.Identifier(column.strip()) for column in column_list.split(",")]
    copy_query = sql.SQL("COPY {} ({}) FROM STDIN WITH ({})").format(
        sql.Identifier(table), sql.SQL(", ").join(columns), sql.SQL(options)
    )

    with (ROOT / relative_path).open("rb") as source:
        with cursor.copy(copy_query) as copy:
            while chunk := source.read(1024 * 1024):
                copy.write(chunk)


def run_script(cursor: psycopg.Cursor[object], path: Path) -> None:
    sql_lines: list[str] = []
    skip_block = False

    for source_line in path.read_text(encoding="utf-8").splitlines():
        line = source_line.strip()
        if line == "-- python-skip-start":
            skip_block = True
            continue
        if line == "-- python-skip-end":
            skip_block = False
            continue
        if skip_block or line.startswith("\\set") or line.startswith("\\connect"):
            continue
        if line.startswith("\\copy"):
            if sql_lines:
                cursor.execute("\n".join(sql_lines))
                sql_lines.clear()
            copy_csv(cursor, line)
            continue
        sql_lines.append(source_line)

    if sql_lines:
        cursor.execute("\n".join(sql_lines))


def main() -> None:
    create_database()
    with psycopg.connect(**connection_parameters(DATABASE), autocommit=True) as connection:
        with connection.cursor() as cursor:
            for script in SCRIPTS:
                print(f"Running {script.relative_to(ROOT)}")
                run_script(cursor, script)
    print("Database scripts completed successfully")


if __name__ == "__main__":
    main()
