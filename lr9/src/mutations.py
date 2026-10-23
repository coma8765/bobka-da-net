from datetime import datetime, timedelta
from time import perf_counter_ns

BASE_TIME = datetime(2026, 1, 1)


class Mutator:
    def __init__(self, repository, service):
        self.repository = repository
        self.service = service

    def change(self, scenario, step, scheduled_seconds):
        source = self.repository.leader_delivery()
        connection = self.repository.connection
        start = perf_counter_ns()
        with connection.transaction():
            if scenario == "insert":
                cursor = connection.execute(
                    "INSERT INTO public.deliveries "
                    "(supplier_id, product_id, warehouse_id, delivered_at, quantity, "
                    "unit_cost, batch_number, quality_status, expires_on) "
                    "VALUES (%s, %s, %s, %s, 100, 100.00, %s, 'accepted', %s) "
                    "RETURNING delivery_id",
                    (
                        source["supplier_id"],
                        source["product_id"],
                        source["warehouse_id"],
                        BASE_TIME + timedelta(seconds=scheduled_seconds),
                        f"LR9-I-{step:06d}",
                        source["expires_on"],
                    ),
                )
            elif scenario == "delete":
                cursor = connection.execute(
                    "DELETE FROM public.deliveries WHERE delivery_id = %s RETURNING delivery_id",
                    (source["delivery_id"],),
                )
            elif scenario == "update":
                cursor = connection.execute(
                    "UPDATE public.deliveries SET quantity = quantity + 100 "
                    "WHERE delivery_id = %s RETURNING delivery_id",
                    (source["delivery_id"],),
                )
            else:
                raise ValueError(f"Unknown mutation: {scenario}")
            if cursor.rowcount != 1:
                raise ValueError("Mutation must affect exactly one delivery")
            delivery_id = cursor.fetchone()[0]
        transaction_ms = (perf_counter_ns() - start) / 1_000_000
        start = perf_counter_ns()
        error = self.service.invalidate()
        invalidation_ms = (perf_counter_ns() - start) / 1_000_000
        return {
            "step": step,
            "scenario": scenario,
            "delivery_id": delivery_id,
            "affected_rows": 1,
            "transaction_ms": transaction_ms,
            "invalidation_ms": invalidation_ms,
            "invalidation_status": "error" if error else ("ok" if self.service.cache else "bypass"),
            "error": error,
        }
