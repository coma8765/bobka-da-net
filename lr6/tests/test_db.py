import unittest
from unittest.mock import MagicMock, patch

import psycopg

try:
    from lr6.src import db
except ModuleNotFoundError as error:
    if error.name != "lr6":
        raise
    from src import db


class ConnectionTests(unittest.TestCase):
    def test_wrong_database_is_rejected_and_connection_closed(self) -> None:
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = ("postgres", "postgres")
        with patch.object(db.psycopg, "connect", return_value=connection):
            with self.assertRaisesRegex(ValueError, "supply_lab"):
                db.connect()
        connection.close.assert_called_once()

    def test_startup_query_failure_closes_connection(self) -> None:
        connection = MagicMock()
        connection.execute.side_effect = psycopg.OperationalError("connection lost")
        with patch.object(db.psycopg, "connect", return_value=connection):
            with self.assertRaises(psycopg.OperationalError):
                db.connect()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
