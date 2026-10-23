import os
from typing import Any

import psycopg


def connect() -> psycopg.Connection[tuple[Any, ...]]:
    connection = psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "55432"),
        dbname=os.getenv("PGDATABASE", "supply_lab"),
        user=os.getenv("PGUSER", "postgres"),
        autocommit=True,
    )
    try:
        database, _ = connection.execute("SELECT current_database(), current_user").fetchone()
        if database != "supply_lab":
            raise ValueError("Приложение работает только с базой supply_lab.")
    except BaseException:
        connection.close()
        raise
    return connection
