import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("static", "insert", "delete", "update")
MODES = ("direct", "cached")


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 55432
    user: str = "postgres"
    password: str = "postgres"
    database: str = "supply_lab_lr9"
    source_database: str = "supply_lab"
    redis_url: str = "redis://127.0.0.1:56379/0"
    postgres_container: str = "lr1-postgres"
    redis_container: str = "lr9-redis"

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("PGHOST", "127.0.0.1"),
            port=int(os.getenv("PGPORT", "55432")),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD", "postgres"),
            database=os.getenv("PGDATABASE", "supply_lab_lr9"),
            source_database=os.getenv("LR9_SOURCE_DATABASE", "supply_lab"),
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:56379/0"),
            postgres_container=os.getenv("LR9_POSTGRES_CONTAINER", "lr1-postgres"),
            redis_container=os.getenv("LR9_REDIS_CONTAINER", "lr9-redis"),
        )

    def connect(self, database=None):
        return psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=database or self.database,
            autocommit=True,
            connect_timeout=5,
            application_name="lr9",
        )

    def validate_target(self):
        if self.database != "supply_lab_lr9" and not self.database.startswith("supply_lab_lr9_"):
            raise ValueError("Target must be supply_lab_lr9 or supply_lab_lr9_<suffix>")
        if self.database == self.source_database:
            raise ValueError("Source and target databases must differ")


@dataclass(frozen=True)
class RunOptions:
    mode: str
    scenario: str
    duration: int = 300
    read_interval: int = 5
    mutation_interval: int = 10
    repeat: int = 1
    ttl: int = 3600
    seed: int = 42

    def validate(self):
        if self.mode not in MODES or self.scenario not in SCENARIOS:
            raise ValueError("Unknown mode or scenario")
        if min(self.duration, self.read_interval, self.mutation_interval, self.repeat) <= 0:
            raise ValueError("Duration, intervals and repeat must be positive")
        if self.duration % self.read_interval or self.duration % self.mutation_interval:
            raise ValueError("Duration must be divisible by both intervals")
        if self.ttl <= self.duration:
            raise ValueError("TTL must exceed duration")
