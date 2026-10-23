import os

from sqlalchemy import URL, Connection, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine() -> Engine:
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "55432")),
        database=os.environ.get("PGDATABASE", "supply_lab"),
    )
    return create_engine(
        url,
        echo=os.environ.get("LR7_SQL_ECHO") == "1",
        connect_args={"connect_timeout": 5},
    )


def make_session_factory(bind: Engine | Connection | None) -> sessionmaker[Session]:
    return sessionmaker(
        bind=bind,
        autoflush=False,
        expire_on_commit=False,
        autobegin=False,
        join_transaction_mode="create_savepoint",
    )
