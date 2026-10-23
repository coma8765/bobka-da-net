import csv
import io
from dataclasses import replace

import pytest

from src.benchmark import MUTATION_FIELDS, READ_FIELDS, events, execute
from src.config import Config, RunOptions
from src.plot_results import summarize
from src.statistics import StatisticsResult


class FakeClock:
    value = 0.0

    def now(self):
        return self.value

    def ticks(self):
        return int(self.value * 1_000_000_000)

    def sleep(self, seconds):
        self.value += seconds


class FakeRepository:
    value = 0

    def top_products(self):
        return [self.value]


class FakeService:
    sql_calls = 0

    def __init__(self, clock, repository, latency=0.1):
        self.clock = clock
        self.repository = repository
        self.latency = latency

    def get(self):
        self.clock.value += self.latency
        self.sql_calls += 1
        return StatisticsResult(self.repository.top_products(), "bypass")


class FakeMutator:
    def __init__(self, repository):
        self.repository = repository

    def change(self, scenario, step, scheduled):
        self.repository.value += 1
        return {"step": step, "error": ""}


def test_default_schedule_counts_and_mutation_order():
    sequence = events(RunOptions("cached", "update"))
    assert sum(kind == "read" for _, kind in sequence) == 61
    assert sum(kind == "mutation" for _, kind in sequence) == 30
    assert [kind for second, kind in sequence if second == 10] == ["mutation", "read"]
    assert len(events(RunOptions("direct", "static"))) == 61


@pytest.mark.parametrize("latency,valid", [(0.1, True), (6, False)])
def test_deadlines_timing_and_overruns(latency, valid):
    clock = FakeClock()
    repository = FakeRepository()
    service = FakeService(clock, repository, latency)
    reads = io.StringIO()
    mutations = io.StringIO()
    read_writer = csv.DictWriter(reads, READ_FIELDS)
    read_writer.writeheader()
    mutation_writer = csv.DictWriter(mutations, MUTATION_FIELDS)
    mutation_writer.writeheader()
    result = execute(
        RunOptions("direct", "update", duration=20),
        service,
        repository,
        FakeMutator(repository),
        read_writer,
        mutation_writer,
        clock,
    )
    assert result["valid"] is valid
    assert result["reads"] == 5
    assert result["mutations"] == 2
    assert result["control_sql_calls"] == 5
    rows = list(csv.DictReader(io.StringIO(reads.getvalue())))
    assert all(row["correct"] == "True" for row in rows)
    assert all(float(row["latency_ms"]) == pytest.approx(latency * 1000) for row in rows)
    if valid:
        assert [float(row["actual_s"]) for row in rows] == [0, 5, 10, 15, 20]


def test_control_query_is_outside_timing():
    clock = FakeClock()
    repository = FakeRepository()
    service = FakeService(clock, repository)
    original = repository.top_products
    service.get = lambda: StatisticsResult([0], "hit")

    def slow_control():
        clock.value += 1
        return original()

    repository.top_products = slow_control
    reads = io.StringIO()
    writer = csv.DictWriter(reads, READ_FIELDS)
    writer.writeheader()
    result = execute(
        RunOptions("cached", "static", duration=10),
        service,
        repository,
        None,
        writer,
        csv.DictWriter(io.StringIO(), MUTATION_FIELDS),
        clock,
    )
    assert result["valid"]
    rows = list(csv.DictReader(io.StringIO(reads.getvalue())))
    assert all(float(row["latency_ms"]) == 0 for row in rows)


@pytest.mark.parametrize(
    "changes",
    [
        {"duration": -10},
        {"duration": 11},
        {"read_interval": 0},
        {"ttl": 300},
        {"repeat": 0},
        {"mode": "other"},
        {"scenario": "other"},
    ],
)
def test_invalid_options(changes):
    with pytest.raises(ValueError):
        replace(RunOptions("direct", "static"), **changes).validate()


def test_source_database_is_protected():
    with pytest.raises(ValueError):
        Config(database="supply_lab").validate_target()
    with pytest.raises(ValueError):
        Config(database="supply_lab_lr9", source_database="supply_lab_lr9").validate_target()


def test_summary_nearest_rank_and_hit_miss():
    rows = [
        {
            "latency_ms": str(i),
            "cache_status": "hit" if i % 2 else "miss",
            "sql_calls": "0" if i % 2 else "1",
            "control_sql_calls": "1",
            "error": "",
            "correct": "True",
        }
        for i in range(1, 21)
    ]
    result = summarize(rows)
    assert result["p95_ms"] == 19
    assert result["mean_ms"] == 10.5
    assert result["hit_rate"] == 0.5
    assert result["hit_mean_ms"] == 10
    assert result["miss_mean_ms"] == 11
    assert result["sql_calls"] == 10
