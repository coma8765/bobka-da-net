import csv
import json

import pytest

from src.benchmark import READ_FIELDS
from src.plot_results import build_report


def sample_run(root, mode, *, valid=True, snapshot="baseline", repeat=1):
    directory = root / f"{mode}-{repeat}"
    directory.mkdir()
    metadata = {
        "run_id": directory.name,
        "valid": valid,
        "status": "completed",
        "scenario": "static",
        "mode": mode,
        "repeat": repeat,
        "snapshot": {"sha256": snapshot},
        "sql_version": "sql-v1",
        "duration": 10,
        "read_interval": 5,
        "mutation_interval": 10,
        "ttl": 3600,
        "seed": 42,
        "row_counts": {"deliveries": 12},
        "machine": "test",
        "python": "3.13",
        "postgres_version": "test",
    }
    (directory / "metadata.json").write_text(json.dumps(metadata))
    with (directory / "measurements.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=READ_FIELDS)
        writer.writeheader()
        for step in range(3):
            hit = mode == "cached" and step > 0
            writer.writerow(
                {
                    "step": step,
                    "scheduled_s": step * 5,
                    "actual_s": step * 5,
                    "lateness_ms": 0,
                    "latency_ms": 1 if hit else 3,
                    "cache_status": "bypass" if mode == "direct" else ("hit" if hit else "miss"),
                    "row_count": 1,
                    "correct": True,
                    "sql_calls": 0 if hit else 1,
                    "control_sql_calls": 1,
                    "error": "",
                }
            )


def test_report_exports_real_artifacts_and_includes_misses(tmp_path):
    sample_run(tmp_path, "direct")
    sample_run(tmp_path, "cached")
    report = build_report(tmp_path)
    assert "Проверочный эксперимент" in report.read_text()
    assert (tmp_path / "summary/static.png").read_bytes().startswith(b"\x89PNG")
    with (tmp_path / "summary/summary.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(float(row["speedup"]) == pytest.approx(1.8) for row in rows)


def test_report_rejects_mixed_snapshots(tmp_path):
    sample_run(tmp_path, "direct")
    sample_run(tmp_path, "cached", snapshot="different")
    with pytest.raises(ValueError, match="different snapshots"):
        build_report(tmp_path)


def test_report_excludes_invalid_runs(tmp_path):
    sample_run(tmp_path, "direct")
    sample_run(tmp_path, "cached", valid=False)
    report = build_report(tmp_path)
    assert "исключено: 1" in report.read_text()
    with (tmp_path / "summary/summary.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["speedup"] == ""
