from dataclasses import dataclass

from redis.exceptions import RedisError


@dataclass
class StatisticsResult:
    rows: list
    cache_status: str
    error: str = ""


class StatisticsService:
    """Sequential use only; no writes may interleave with get()/invalidate()."""

    def __init__(self, repository, cache=None):
        self.repository = repository
        self.cache = cache
        self.invalidation_pending = False
        self.sql_calls = 0

    def invalidate(self):
        if self.cache is None:
            return ""
        self.invalidation_pending = True
        try:
            self.cache.invalidate()
        except RedisError as exc:
            return type(exc).__name__
        self.invalidation_pending = False
        return ""

    def query_database(self):
        self.sql_calls += 1
        return self.repository.top_products()

    def get(self):
        if self.cache is None:
            return StatisticsResult(self.query_database(), "bypass")
        try:
            if self.invalidation_pending:
                self.cache.invalidate()
                self.invalidation_pending = False
            rows = self.cache.get()
            if rows is not None:
                return StatisticsResult(rows, "hit")
        except RedisError as exc:
            return StatisticsResult(self.query_database(), "fallback", type(exc).__name__)
        rows = self.query_database()
        try:
            self.cache.put(rows)
        except RedisError as exc:
            return StatisticsResult(rows, "fallback", type(exc).__name__)
        return StatisticsResult(rows, "miss")
