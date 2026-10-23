import csv
import json
import platform
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from .cache import StatisticsCache, redis_client
from .mutations import Mutator
from .repository import SQL_VERSION, Repository
from .statistics import StatisticsService

READ_FIELDS = (
    "step",
    "scheduled_s",
    "actual_s",
    "lateness_ms",
    "latency_ms",
    "cache_status",
    "row_count",
    "correct",
    "sql_calls",
    "control_sql_calls",
    "error",
)
MUTATION_FIELDS = (
    "step",
    "scenario",
    "scheduled_s",
    "actual_s",
    "delivery_id",
    "affected_rows",
    "transaction_ms",
    "invalidation_ms",
    "invalidation_status",
    "error",
)


def events(options):
    options.validate()
    pending = [(second, "read") for second in range(0, options.duration + 1, options.read_interval)]
    if options.scenario != "static":
        pending += [
            (second, "mutation")
            for second in range(
                options.mutation_interval, options.duration + 1, options.mutation_interval
            )
        ]
    return sorted(pending)  # 'mutation' sorts before 'read' at the same deadline.


class Clock:
    now = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    ticks = staticmethod(time.perf_counter_ns)


def execute(options, service, repository, mutator, read_writer, mutation_writer, clock=None):
    clock = clock or Clock()
    start = clock.now()
    previous_finish = start
    previous_deadline = None
    read_step = mutation_step = controls = 0
    errors = []
    schedule_violations = 0
    for scheduled, kind in events(options):
        deadline = start + scheduled
        if previous_deadline != deadline and previous_finish > deadline:
            schedule_violations += 1
        clock.sleep(max(0, deadline - clock.now()))
        actual = clock.now() - start
        if kind == "mutation":
            mutation_step += 1
            try:
                result = mutator.change(options.scenario, mutation_step, scheduled)
            except Exception as exc:
                mutation_writer.writerow(
                    {
                        "step": mutation_step,
                        "scenario": options.scenario,
                        "scheduled_s": scheduled,
                        "actual_s": actual,
                        "error": type(exc).__name__,
                    }
                )
                raise
            mutation_writer.writerow({**result, "scheduled_s": scheduled, "actual_s": actual})
            if result["error"]:
                errors.append(result["error"])
        else:
            begin = clock.ticks()
            calls_before = service.sql_calls
            try:
                result = service.get()
                elapsed = (clock.ticks() - begin) / 1_000_000
                control = repository.top_products()
                controls += 1
                correct = result.rows == control
                error = result.error or ("ResultMismatch" if not correct else "")
            except Exception as exc:
                read_writer.writerow(
                    {
                        "step": read_step,
                        "scheduled_s": scheduled,
                        "actual_s": actual,
                        "lateness_ms": max(0, (actual - scheduled) * 1000),
                        "error": type(exc).__name__,
                    }
                )
                raise
            read_writer.writerow(
                {
                    "step": read_step,
                    "scheduled_s": scheduled,
                    "actual_s": actual,
                    "lateness_ms": max(0, (actual - scheduled) * 1000),
                    "latency_ms": elapsed,
                    "cache_status": result.cache_status,
                    "row_count": len(result.rows),
                    "correct": correct,
                    "sql_calls": service.sql_calls - calls_before,
                    "control_sql_calls": 1,
                    "error": error,
                }
            )
            read_step += 1
            if error:
                errors.append(error)
            if not correct:
                raise ValueError("Cached result differs from the control SQL")
        previous_finish = clock.now()
        previous_deadline = deadline
    return {
        "reads": read_step,
        "mutations": mutation_step,
        "sql_calls": service.sql_calls,
        "control_sql_calls": controls,
        "schedule_violations": schedule_violations,
        "errors": errors,
        "valid": not errors and not schedule_violations,
    }


def run_benchmark(config, options, output, snapshot, images):
    options.validate()
    run_id = f"{options.scenario}-{options.mode}-r{options.repeat}-{uuid4().hex[:12]}"
    directory = Path(output) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {
        **asdict(options),
        "run_id": run_id,
        "snapshot": snapshot,
        "images": images,
        "started_at": datetime.now(UTC).isoformat(),
        "sql_version": SQL_VERSION,
        "machine": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("psycopg", "redis", "matplotlib")},
        "valid": False,
        "status": "preparing",
        "selection": "deterministic leader/minimum delivery_id; seed reserved, no randomness",
    }
    metadata_path = directory / "metadata.json"

    def save():
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    save()
    client = None
    try:
        with config.connect() as connection:
            repository = Repository(connection)
            metadata.update(repository.describe())
            metadata["postgres_version"] = connection.execute("SELECT version()").fetchone()[0]
            repository.preflight(options.scenario, options.duration // options.mutation_interval)
            cache = None
            if options.mode == "cached":
                client = redis_client(config.redis_url)
                client.ping()
                metadata["redis_version"] = client.info("server")["redis_version"]
                cache = StatisticsCache(client, run_id, options.ttl)
                cache.invalidate()
            for _ in range(5):
                repository.top_products()
            service = StatisticsService(repository, cache)
            mutator = Mutator(repository, service)
            with (
                (directory / "measurements.csv").open("w", newline="") as read_file,
                (directory / "mutations.csv").open("w", newline="") as mutation_file,
            ):
                reads = csv.DictWriter(read_file, fieldnames=READ_FIELDS)
                mutations = csv.DictWriter(mutation_file, fieldnames=MUTATION_FIELDS)
                reads.writeheader()
                mutations.writeheader()
                metadata["status"] = "running"
                save()
                metadata.update(execute(options, service, repository, mutator, reads, mutations))
            metadata["status"] = "completed"
    except BaseException as exc:
        metadata.update(valid=False, status="failed", failure=type(exc).__name__)
        raise
    finally:
        if client is not None:
            client.close()
        metadata["finished_at"] = datetime.now(UTC).isoformat()
        save()
    return directory, metadata
