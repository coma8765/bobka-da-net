import time
from unittest.mock import patch

import psycopg
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.mutations import Mutator
from src.statistics import StatisticsService

pytestmark = pytest.mark.integration


def test_hit_does_not_query_postgres(repository, cache):
    service = StatisticsService(repository, cache)
    first = service.get()
    assert first.cache_status == "miss"
    with patch.object(repository, "top_products", side_effect=AssertionError("Unexpected SQL")):
        second = service.get()
    assert second.cache_status == "hit"
    assert second.rows == first.rows
    assert service.sql_calls == 1


@pytest.mark.parametrize("scenario", ["insert", "delete", "update"])
def test_commit_invalidates_and_changes_result(repository, cache, scenario):
    service = StatisticsService(repository, cache)
    before = service.get()
    mutation = Mutator(repository, service).change(scenario, 1, 10)
    assert mutation["affected_rows"] == 1
    assert mutation["invalidation_status"] == "ok"
    after = service.get()
    assert after.cache_status == "miss"
    assert after.rows == repository.top_products()
    assert after.rows != before.rows
    assert service.get().cache_status == "hit"


def test_rollback_preserves_cache(repository, cache):
    service = StatisticsService(repository, cache)
    mutator = Mutator(repository, service)
    mutator.change("insert", 1, 10)
    before = service.get().rows
    with pytest.raises(psycopg.errors.UniqueViolation):
        mutator.change("insert", 1, 10)
    after = service.get()
    assert after.cache_status == "hit"
    assert after.rows == before == repository.top_products()


def test_expiry_corruption_and_missing_key(repository, cache):
    service = StatisticsService(repository, cache)
    expected = service.get().rows
    cache.client.pexpire(cache.key, 1)
    time.sleep(0.02)
    assert service.get().cache_status == "miss"
    for payload in (
        b"{",
        b"\xff",
        b"null",
        b'{"schema_version":2,"rows":[]}',
        b'{"schema_version":1,"rows":[{}]}',
    ):
        cache.client.set(cache.key, payload)
        result = service.get()
        assert result.cache_status == "miss"
        assert result.rows == expected
    cache.invalidate()
    assert service.get().cache_status == "miss"


def test_failed_delete_never_reads_stale_cache_or_repeats_write(repository, cache):
    service = StatisticsService(repository, cache)
    stale = service.get().rows
    mutator = Mutator(repository, service)
    with patch.object(cache.client, "delete", side_effect=RedisConnectionError("offline")):
        mutation = mutator.change("update", 1, 10)
        assert mutation["error"] == "ConnectionError"
        current = repository.top_products()
        assert current != stale
        assert cache.get() == stale
        with patch.object(cache, "get", side_effect=AssertionError("Stale key must not be read")):
            result = service.get()
        assert result.cache_status == "fallback"
        assert result.rows == current
    result = service.get()
    assert result.cache_status == "miss"
    assert result.rows == current == repository.top_products()
    assert not service.invalidation_pending


@pytest.mark.parametrize("operation", ["get", "set"])
def test_redis_failure_falls_back(repository, cache, operation):
    service = StatisticsService(repository, cache)
    with patch.object(cache.client, operation, side_effect=RedisConnectionError("offline")):
        result = service.get()
    assert result.cache_status == "fallback"
    assert result.rows == repository.top_products()
    assert service.sql_calls == 1


def test_postgres_error_is_not_hidden(repository, cache):
    service = StatisticsService(repository, cache)
    with patch.object(repository, "top_products", side_effect=psycopg.OperationalError("offline")):
        with pytest.raises(psycopg.OperationalError):
            service.get()


def test_sql_top_ten_ties_statuses_exact_cost_and_empty_cache(repository, cache):
    connection = repository.connection
    # Dedicated disposable database; remove dependent LR5 test documents too.
    connection.execute("TRUNCATE public.deliveries CASCADE")
    service = StatisticsService(repository, cache)
    assert service.get().rows == []
    assert service.get().cache_status == "hit"
    supplier = connection.execute("SELECT min(supplier_id) FROM public.suppliers").fetchone()[0]
    warehouse = connection.execute("SELECT min(warehouse_id) FROM public.warehouses").fetchone()[0]
    products = connection.execute(
        "SELECT product_id FROM public.products ORDER BY product_id LIMIT 12"
    ).fetchall()
    for index, (product,) in enumerate(products):
        for status, quantity in (("accepted", 3), ("rejected", 999), ("inspection", 999)):
            connection.execute(
                "INSERT INTO public.deliveries "
                "(supplier_id, product_id, warehouse_id, delivered_at, quantity, unit_cost, "
                "batch_number, quality_status) VALUES (%s, %s, %s, '2026-01-01', %s, "
                "0.10, %s, %s)",
                (supplier, product, warehouse, quantity, f"T{index}-{status}", status),
            )
    service.invalidate()
    rows = service.get().rows
    assert len(rows) == 10
    assert [row["product_id"] for row in rows] == [row[0] for row in products[:10]]
    assert all(row["total_cost"] == "0.30" and row["delivery_count"] == 1 for row in rows)
