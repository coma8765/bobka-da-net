import pytest

from src.config import ROOT
from src.repository import Repository
from src.snapshot import restore_snapshot

pytestmark = pytest.mark.integration


def state(config):
    with config.connect() as connection:
        return (
            Repository(connection).top_products(),
            connection.execute(
                "SELECT schemaname, sequencename, last_value FROM pg_sequences "
                "ORDER BY schemaname, sequencename"
            ).fetchall(),
        )


def test_restore_includes_rows_and_sequences(database_config):
    before = state(database_config)
    with database_config.connect() as connection:
        connection.execute(
            "SELECT nextval(pg_get_serial_sequence('public.deliveries', 'delivery_id'))"
        )
        connection.execute("UPDATE public.deliveries SET quantity = quantity + 1")
    assert state(database_config) != before
    restore_snapshot(database_config, ROOT / "snapshots/baseline.dump")
    assert state(database_config) == before
