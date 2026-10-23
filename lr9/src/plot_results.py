import csv
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path

from .config import ROOT, SCENARIOS


def summarize(rows):
    values = [float(row["latency_ms"]) for row in rows if row["latency_ms"]]
    if not values:
        return {}
    ordered = sorted(values)
    hits = [float(row["latency_ms"]) for row in rows if row["cache_status"] == "hit"]
    misses = [float(row["latency_ms"]) for row in rows if row["cache_status"] == "miss"]
    return {
        "count": len(values),
        "mean_ms": statistics.mean(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "min_ms": min(values),
        "max_ms": max(values),
        "hit_rate": len(hits) / len(rows),
        "hit_mean_ms": statistics.mean(hits) if hits else "",
        "miss_mean_ms": statistics.mean(misses) if misses else "",
        "sql_calls": sum(int(row["sql_calls"] or 0) for row in rows),
        "control_sql_calls": sum(int(row["control_sql_calls"] or 0) for row in rows),
        "errors": sum(bool(row["error"]) for row in rows),
        "mismatches": sum(row["correct"] == "False" for row in rows),
    }


def build_report(results, report_path=None):
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    results = Path(results).resolve()
    summary_dir = results / "summary"
    summary_dir.mkdir(exist_ok=True)
    runs = []
    excluded = []
    # This enumerates generated measurement artifacts, not source files.
    for directory in sorted(results.iterdir()):
        path = directory / "metadata.json"
        if not path.is_file():
            continue
        metadata = json.loads(path.read_text())
        if not metadata.get("valid") or metadata.get("status") != "completed":
            excluded.append(metadata["run_id"])
            continue
        with (directory / "measurements.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        runs.append((metadata, rows, summarize(rows)))
    if not runs:
        raise ValueError("No valid completed runs to summarize")
    conditions = {
        (
            m["snapshot"]["sha256"],
            m["sql_version"],
            m["duration"],
            m["read_interval"],
            m["mutation_interval"],
            m["ttl"],
            m["seed"],
        )
        for m, _, _ in runs
    }
    if len(conditions) != 1:
        raise ValueError(
            "Results have different snapshots, SQL or timing; use separate directories"
        )
    pairs = defaultdict(dict)
    for metadata, rows, summary in runs:
        key = (metadata["scenario"], metadata["repeat"])
        if metadata["mode"] in pairs[key]:
            raise ValueError("Duplicate scenario/mode/repeat; use a fresh results directory")
        pairs[key][metadata["mode"]] = (metadata, rows, summary)
    records = []
    for metadata, _, summary in runs:
        pair = pairs[(metadata["scenario"], metadata["repeat"])]
        speedup = ""
        if "direct" in pair and "cached" in pair:
            speedup = pair["direct"][2]["mean_ms"] / pair["cached"][2]["mean_ms"]
        records.append(
            {
                "scenario": metadata["scenario"],
                "mode": metadata["mode"],
                "repeat": metadata["repeat"],
                **summary,
                "speedup": speedup,
            }
        )
    with (summary_dir / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.2})
    for scenario in SCENARIOS:
        repeats = sorted(repeat for name, repeat in pairs if name == scenario)
        if not repeats:
            continue
        figure, axes = plt.subplots(
            len(repeats),
            1,
            figsize=(11, 3.2 * len(repeats)),
            sharex=True,
            sharey=True,
            squeeze=False,
            constrained_layout=True,
        )
        for axis, repeat in zip(axes[:, 0], repeats, strict=True):
            for mode, color in (("direct", "#245ea8"), ("cached", "#d45d00")):
                if mode not in pairs[(scenario, repeat)]:
                    continue
                metadata, rows, _ = pairs[(scenario, repeat)][mode]
                axis.plot(
                    [float(row["actual_s"]) for row in rows],
                    [float(row["latency_ms"]) for row in rows],
                    label=mode,
                    color=color,
                    linewidth=1.4,
                    alpha=0.85,
                )
                if mode == "cached":
                    for status, marker in (("hit", "o"), ("miss", "X")):
                        selected = [row for row in rows if row["cache_status"] == status]
                        axis.scatter(
                            [float(row["actual_s"]) for row in selected],
                            [float(row["latency_ms"]) for row in selected],
                            label=status,
                            marker=marker,
                            color=color,
                            s=28,
                            zorder=3,
                        )
            if scenario != "static":
                for second in range(
                    metadata["mutation_interval"],
                    metadata["duration"] + 1,
                    metadata["mutation_interval"],
                ):
                    axis.axvline(second, color="#777777", linestyle=":", alpha=0.35)
            axis.set_title(f"{scenario} / repeat {repeat}", loc="left")
            axis.set_ylabel("Latency, ms")
            axis.set_ylim(bottom=0)
            axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
        axes[-1, 0].set_xlabel("Elapsed time, seconds")
        figure.savefig(summary_dir / f"{scenario}.png", dpi=160)
        plt.close(figure)

    first = runs[0][0]
    report_path = Path(report_path) if report_path else summary_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    complete = len(runs) == 24 and all(
        (scenario, repeat) in pairs and set(pairs[(scenario, repeat)]) == {"direct", "cached"}
        for scenario in SCENARIOS
        for repeat in (1, 2, 3)
    )
    full = (
        complete
        and first["duration"] == 300
        and first["read_interval"] == 5
        and (first["mutation_interval"] == 10)
    )
    lines = [
        "# ЛР9: результаты сравнения PostgreSQL и Redis",
        "",
        "Полный эксперимент RFC завершён."
        if full
        else "Проверочный эксперимент. Эти результаты не заменяют 24 прогона по 300 секунд из RFC.",
        "",
        "## Условия",
        "",
        f"- Корректных прогонов: {len(runs)}; исключено: {len(excluded)}.",
        f"- Длительность: {first['duration']} с; чтение каждые {first['read_interval']} с; "
        f"изменение каждые {first['mutation_interval']} с.",
        f"- TTL: {first['ttl']} с; пять прогревочных SQL перед каждым прогоном.",
        f"- Исходные количества строк: `{json.dumps(first['row_counts'], ensure_ascii=False)}`.",
        f"- SHA-256 снимка: `{first['snapshot']['sha256']}`.",
        "- После восстановления в экспериментальной копии очищается "
        "`lr5.delivery_documents`: её FK запрещает удаление всех исходных поставок. "
        "Данные ЛР1 и ограничения сохраняются; основная БД не изменяется.",
        f"- Версия SQL: `{first['sql_version']}`.",
        f"- Среда: {first['machine']}; Python {first['python']}.",
        f"- PostgreSQL: {first['postgres_version']}.",
        "",
        "Время включает получение и преобразование результата, а при miss также "
        "заполнение Redis. Соединения, запись, инвалидация и контрольный SQL не входят "
        "в интервал. После каждого чтения выполнен контрольный SQL: это дополнительно "
        "прогревает PostgreSQL в обоих режимах. Первый miss включён. "
        "p95 вычислен методом nearest-rank. Изменения выполнялись до чтения на общем дедлайне.",
        "",
        "## Сводные показатели",
        "",
        "| Сценарий | Режим | Повтор | n | Mean, мс | Median, мс | p95, мс | Hit rate | "
        "SQL сервиса | Ускорение |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(records, key=lambda item: (item["scenario"], item["repeat"], item["mode"])):
        speed = f"{row['speedup']:.2f}×" if row["speedup"] != "" else "—"
        lines.append(
            f"| {row['scenario']} | {row['mode']} | {row['repeat']} | {row['count']} | "
            f"{row['mean_ms']:.3f} | {row['median_ms']:.3f} | {row['p95_ms']:.3f} | "
            f"{row['hit_rate']:.1%} | {row['sql_calls']} | {speed} |"
        )
    lines += [
        "",
        "Ускорение — mean(direct) / mean(cached) внутри одного повтора; "
        "включает промахи. Min/max, длительности hit/miss, ошибки и контрольные "
        "SQL сохранены в `summary.csv`.",
        "",
        "## Графики и выводы",
        "",
    ]
    for scenario in SCENARIOS:
        speeds = [
            r["speedup"]
            for r in records
            if r["scenario"] == scenario and r["mode"] == "cached" and r["speedup"] != ""
        ]
        if not speeds:
            continue
        image = os.path.relpath(summary_dir / f"{scenario}.png", report_path.parent)
        lines += [
            f"### {scenario}",
            "",
            f"![Время выполнения: {scenario}]({image})",
            "",
            f"Диапазон ускорения по повторам: {min(speeds):.2f}–{max(speeds):.2f}×.",
            "",
        ]
    lines += [
        "На статических данных кэш заполняется один раз. При изменениях каждая "
        "подтверждённая запись инвалидирует ключ; следующее чтение выполняет SQL "
        "и заполняет Redis. Поэтому выигрыш от попаданий нужно оценивать вместе "
        "со стоимостью промахов. Коэффициент ниже 1 означает замедление.",
        "",
        "Измерения относятся к локальному стенду, указанному объёму данных и "
        "прогретой PostgreSQL. Малое число точек в коротком прогоне делает p95 "
        "чувствительным к единичным задержкам. Версии пакетов, образы и ограничения "
        "БД доступны в metadata.json каждого прогона.",
        "",
    ]
    if excluded:
        lines += ["Исключённые прогоны: " + ", ".join(excluded) + ".", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
