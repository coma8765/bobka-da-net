import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .benchmark import run_benchmark
from .config import MODES, ROOT, SCENARIOS, Config, RunOptions
from .mutations import Mutator
from .plot_results import build_report
from .repository import Repository
from .snapshot import create_snapshot, exclusive_target, image_metadata, restore_snapshot
from .statistics import StatisticsService


def validate_mutations(config, options):
    """Exercise all mutations, including existing triggers/FKs, before timing."""
    with config.connect() as connection:
        repository = Repository(connection)
        steps = options.duration // options.mutation_interval
        repository.preflight(options.scenario, steps)
        if options.scenario != "static":
            with connection.transaction(force_rollback=True):
                mutator = Mutator(repository, StatisticsService(repository))
                for step in range(1, steps + 1):
                    mutator.change(options.scenario, step, step * options.mutation_interval)
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def parser():
    result = argparse.ArgumentParser(description="ЛР9: статистика поставок и Redis-кэш")
    commands = result.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser(
        "snapshot", help="Create a read-only dump of the source database"
    )
    snapshot.add_argument("--snapshot", type=Path, default=ROOT / "snapshots/baseline.dump")
    restore = commands.add_parser("restore", help="Restore only the managed LR9 copy")
    restore.add_argument("--snapshot", type=Path, default=ROOT / "snapshots/baseline.dump")
    for name in ("run", "matrix"):
        command = commands.add_parser(name)
        command.add_argument("--snapshot", type=Path, default=ROOT / "snapshots/baseline.dump")
        command.add_argument("--output", type=Path, default=ROOT / "results/full")
        command.add_argument("--duration", type=int, default=300)
        command.add_argument("--read-interval", type=int, default=5)
        command.add_argument("--mutation-interval", type=int, default=10)
        command.add_argument("--ttl", type=int, default=3600)
        command.add_argument("--seed", type=int, default=42)
        if name == "run":
            command.add_argument("--mode", choices=MODES, required=True)
            command.add_argument("--scenario", choices=SCENARIOS, required=True)
            command.add_argument("--repeat", type=int, default=1)
        else:
            command.add_argument("--repeats", type=int, default=3)
    plot = commands.add_parser("plot")
    plot.add_argument("--output", type=Path, default=ROOT / "results/full")
    plot.add_argument("--report", type=Path)
    return result


def main():
    args = parser().parse_args()
    config = Config.from_env()
    if args.command == "plot":
        print(build_report(args.output, args.report))
        return 0
    with exclusive_target(config):
        if args.command == "snapshot":
            print(json.dumps(create_snapshot(config, args.snapshot), indent=2))
            return 0
        if args.command == "restore":
            print(json.dumps(restore_snapshot(config, args.snapshot), indent=2))
            return 0
        options = RunOptions(
            mode=getattr(args, "mode", "direct"),
            scenario=getattr(args, "scenario", "static"),
            duration=args.duration,
            read_interval=args.read_interval,
            mutation_interval=args.mutation_interval,
            repeat=getattr(args, "repeat", 1),
            ttl=args.ttl,
            seed=args.seed,
        )
        options.validate()
        if args.command == "matrix" and args.repeats <= 0:
            raise ValueError("Repeats must be positive")
        images = image_metadata(config)
        plan = [options]
        if args.command == "matrix":
            if args.output.exists() and any(args.output.iterdir()):
                raise ValueError("Matrix output must be a new or empty directory")
            plan = [
                replace(options, mode=mode, scenario=scenario, repeat=repeat)
                for repeat in range(1, args.repeats + 1)
                for scenario in SCENARIOS
                for mode in (MODES if repeat % 2 else tuple(reversed(MODES)))
            ]
        # Preflight every scenario before any long-running measurement.
        for scenario in dict.fromkeys(item.scenario for item in plan):
            restore_snapshot(config, args.snapshot)
            validate_mutations(config, replace(options, scenario=scenario))
        failed = False
        for index, item in enumerate(plan, 1):
            snapshot = restore_snapshot(config, args.snapshot)
            print(f"[{index}/{len(plan)}] {item.scenario}/{item.mode}/r{item.repeat}", flush=True)
            directory, metadata = run_benchmark(config, item, args.output, snapshot, images)
            failed |= not metadata["valid"]
            print(f"  {directory.name}: valid={metadata['valid']}", flush=True)
        if args.command == "matrix":
            print(build_report(args.output))
        return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted; partial results have been retained.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
