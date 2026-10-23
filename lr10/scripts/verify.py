"""Check provisioned Grafana panels against independently aggregated PostgreSQL rows."""

import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def request(path, credentials, body=None):
    authorization = base64.b64encode(credentials.encode()).decode()
    req = urllib.request.Request(
        "http://127.0.0.1:3000" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Basic " + authorization,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def epoch(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def query_rows(result):
    if result.get("error"):
        raise AssertionError(result["error"])
    rows = []
    for frame in result.get("frames", []):
        names = [field["name"] for field in frame["schema"]["fields"]]
        rows.extend(dict(zip(names, values)) for values in zip(*frame["data"]["values"]))
    return rows


def verify():
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    credentials = env.get("GRAFANA_ADMIN_USER", "admin") + ":" + env["GRAFANA_ADMIN_PASSWORD"]
    health = request("/api/datasources/uid/supply-lab-postgres/health", credentials)
    assert health["status"] == "OK", health
    dashboard = request("/api/dashboards/uid/supply-overview", credentials)["dashboard"]
    assert len(dashboard["panels"]) == 6
    assert dashboard["timezone"] == "utc"
    assert {p["type"] for p in dashboard["panels"]} >= {"table", "timeseries", "barchart"}

    # Fetch unaggregated source data through a separate, authenticated SQL connection.
    sql = """
    SELECT json_build_object(
        'deliveries', (SELECT json_agg(d) FROM public.deliveries d),
        'warehouses', (SELECT json_agg(w) FROM public.warehouses w),
        'suppliers', (SELECT json_agg(s) FROM public.suppliers s),
        'products', (SELECT json_agg(p) FROM public.products p),
        'timezone', current_setting('timezone'),
        'can_write', has_table_privilege(current_user, 'public.deliveries', 'INSERT,UPDATE,DELETE')
    );
    """
    raw = subprocess.run(
        ["podman", "exec", "--env", "PGPASSWORD", "lr1-postgres", "psql", "-X", "-A", "-t",
         "-h", "127.0.0.1", "-U", "grafana_reader", "-d", "supply_lab",
         "-v", "ON_ERROR_STOP=1", "-c", sql],
        env={**os.environ, "PGPASSWORD": env["GRAFANA_DB_PASSWORD"]},
        check=True, capture_output=True, text=True,
    )
    source = json.loads(raw.stdout, parse_float=Decimal)
    assert source["timezone"] == "UTC" and not source["can_write"]
    warehouses = {row["warehouse_id"]: row for row in source["warehouses"]}
    suppliers = {row["supplier_id"]: row for row in source["suppliers"]}
    products = {row["product_id"]: row for row in source["products"]}
    assert -1 not in warehouses
    initial_counts = Counter(
        row["warehouse_id"] for row in source["deliveries"]
        if "2025-01-01" <= row["delivered_at"] < "2026-09-05"
    )
    assert initial_counts, "No deliveries in the initial dashboard period"
    chosen = initial_counts.most_common(1)[0][0]
    cases = [
        ("initial", -1, "2025-01-01", "2026-09-05"),
        ("warehouse", chosen, "2025-01-01", "2026-09-05"),
        ("short_period", -1, "2025-06-01", "2025-06-08"),
        ("empty", -1, "2000-01-01", "2000-01-02"),
        ("all_current_data", -1, "2025-01-01", "2026-10-01"),
    ]
    for name, warehouse, start, end in cases:
        queries = []
        for panel in dashboard["panels"]:
            target = dict(panel["targets"][0])
            target.update(refId=str(panel["id"]), intervalMs=86400000, maxDataPoints=10000)
            target["rawSql"] = target["rawSql"].replace("${warehouse:sqlstring}", "'" + str(warehouse) + "'")
            queries.append(target)
        response = request("/api/ds/query", credentials, {
            "from": str(epoch(start)), "to": str(epoch(end)), "queries": queries,
        })
        actual = {int(key): query_rows(value) for key, value in response["results"].items()}
        selected = [row for row in source["deliveries"]
                    if epoch(start) <= epoch(row["delivered_at"]) <= epoch(end)
                    and (warehouse == -1 or row["warehouse_id"] == warehouse)]
        total = sum((row["quantity"] * row["unit_cost"] for row in selected), Decimal(0))
        rejected = sum(row["quality_status"] == "rejected" for row in selected)
        assert actual[1][0]["delivery_count"] == len(selected), name
        assert abs(Decimal(str(actual[2][0]["total_cost"])) - total) < Decimal("0.001"), name
        if selected:
            assert abs(actual[3][0]["rejected_percent"] - 100 * rejected / len(selected)) < 1e-8, name
        else:
            assert actual[3][0]["rejected_percent"] is None, name

        daily = defaultdict(lambda: {"accepted": 0, "inspection": 0, "rejected": 0})
        costs = defaultdict(Decimal)
        for row in selected:
            daily[epoch(row["delivered_at"][:10])][row["quality_status"]] += 1
            costs[row["warehouse_id"]] += row["quantity"] * row["unit_cost"]
        actual_daily = {row["Time"]: {status: row[status] for status in ["accepted", "inspection", "rejected"]}
                        for row in actual[4]}
        assert actual_daily == dict(daily), (name, "daily series")
        top = sorted(costs, key=lambda key: (-costs[key], key))[:10]
        assert len(actual[5]) == len(top), name
        for row, key in zip(actual[5], top):
            assert row["warehouse"] == warehouses[key]["code"] + " — " + warehouses[key]["name"], name
            assert abs(Decimal(str(row["total_cost"])) - costs[key]) < Decimal("0.001"), name

        latest = sorted(selected, key=lambda row: (row["delivered_at"], row["delivery_id"]), reverse=True)[:100]
        assert [row["delivery_id"] for row in actual[6]] == [row["delivery_id"] for row in latest], name
        for row, expected in zip(actual[6], latest):
            assert row["supplier"] == suppliers[expected["supplier_id"]]["name"], name
            assert row["product"] == products[expected["product_id"]]["name"], name
            assert row["unit"] == products[expected["product_id"]]["unit"], name
            assert row["warehouse_code"] == warehouses[expected["warehouse_id"]]["code"], name
            assert row["delivered_at"] == epoch(expected["delivered_at"]), name
        print(f"PASS {name}: warehouse={warehouse}, count={len(selected)}, cost={total}")

    variable = dashboard["templating"]["list"][0]
    response = request("/api/ds/query", credentials, {
        "from": str(epoch("2025-01-01")), "to": str(epoch("2026-09-05")),
        "queries": [{"refId": "variable", "datasource": variable["datasource"],
                     "rawSql": variable["query"], "format": "table"}],
    })
    options = query_rows(response["results"]["variable"])
    assert options[0] == {"__text": "Все склады", "__value": "-1"}
    assert len(options) == len(warehouses) + 1
    print("PASS datasource health, six panels, UTC, reader permissions and warehouse variable")


if __name__ == "__main__":
    verify()
