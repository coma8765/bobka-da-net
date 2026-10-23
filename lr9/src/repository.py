import hashlib

from psycopg import sql
from psycopg.rows import dict_row

from .config import ROOT

TOP_SQL = (ROOT / "queries/top_products.sql").read_text(encoding="utf-8")
SQL_VERSION = hashlib.sha256(TOP_SQL.encode()).hexdigest()
TABLES = ("suppliers", "products", "warehouses", "warehouse_sections", "deliveries")


class Repository:
    def __init__(self, connection):
        self.connection = connection

    def top_products(self):
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(TOP_SQL).fetchall()
        return [{**row, "total_cost": format(row["total_cost"], ".2f")} for row in rows]

    def leader_delivery(self):
        rows = self.top_products()
        if not rows:
            raise ValueError("No accepted deliveries")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                "SELECT * FROM public.deliveries "
                "WHERE product_id = %s AND quality_status = 'accepted' "
                "ORDER BY delivery_id LIMIT 1",
                (rows[0]["product_id"],),
            ).fetchone()

    def describe(self):
        counts = {
            table: self.connection.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in TABLES
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            constraints = cursor.execute(
                "SELECT conname, pg_get_constraintdef(oid) AS definition "
                "FROM pg_constraint WHERE conrelid IN "
                "('public.deliveries'::regclass, 'public.products'::regclass) "
                "ORDER BY conname"
            ).fetchall()
            triggers = cursor.execute(
                "SELECT tgname, pg_get_triggerdef(oid) AS definition "
                "FROM pg_trigger WHERE tgrelid = 'public.deliveries'::regclass "
                "AND NOT tgisinternal ORDER BY tgname"
            ).fetchall()
        return {"row_counts": counts, "constraints": constraints, "triggers": triggers}

    def preflight(self, scenario, steps):
        accepted = self.connection.execute(
            "SELECT count(*) FROM public.deliveries WHERE quality_status = 'accepted'"
        ).fetchone()[0]
        if scenario != "static" and not accepted:
            raise ValueError("Mutations require accepted deliveries")
        if scenario == "delete" and accepted <= steps:
            raise ValueError("Not enough accepted deliveries for the delete scenario")
        if (
            scenario == "insert"
            and self.connection.execute(
                "SELECT EXISTS (SELECT 1 FROM public.deliveries WHERE batch_number LIKE 'LR9-I-%')"
            ).fetchone()[0]
        ):
            raise ValueError("Reserved batch numbers LR9-I-* already exist")
        if steps > 999999:
            raise ValueError("Too many mutation steps")
        if scenario == "update":
            maximum = self.connection.execute(
                "SELECT coalesce(max(quantity), 0) FROM public.deliveries"
            ).fetchone()[0]
            if maximum + steps * 100 > 2147483647:
                raise ValueError("Quantity could overflow integer")
