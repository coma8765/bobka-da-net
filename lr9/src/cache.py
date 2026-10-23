import json
import re

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


def redis_client(url):
    return Redis.from_url(
        url,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry=Retry(NoBackoff(), 0),
        decode_responses=False,
    )


class StatisticsCache:
    def __init__(self, client, run_id, ttl=3600):
        self.client = client
        self.key = f"lr9:{run_id}:stats:top-products-by-cost:v1"
        self.ttl = ttl

    def get(self):
        raw = self.client.get(self.key)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
                return None
            rows = value.get("rows")
            if value["schema_version"] != 1 or not isinstance(rows, list) or len(rows) > 10:
                return None
            expected = {"product_id", "sku", "name", "delivery_count", "total_cost"}
            for row in rows:
                if not isinstance(row, dict) or set(row) != expected:
                    return None
                if any(type(row[field]) is not int for field in ("product_id", "delivery_count")):
                    return None
                if row["delivery_count"] <= 0:
                    return None
                if any(not isinstance(row[field], str) for field in ("sku", "name", "total_cost")):
                    return None
                if not re.fullmatch(r"[0-9]+\.[0-9]{2}", row["total_cost"]):
                    return None
            return rows
        except (ValueError, UnicodeError):
            return None

    def put(self, rows):
        self.client.set(
            self.key,
            json.dumps({"schema_version": 1, "rows": rows}, ensure_ascii=False),
            ex=self.ttl,
        )

    def invalidate(self):
        self.client.delete(self.key)
