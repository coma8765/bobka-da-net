#!/usr/bin/env python3
"""Generate deterministic CSV fixtures for the supply database."""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path


COUNTRIES_AND_CITIES = (
    ("Russia", "Moscow"),
    ("Russia", "Saint Petersburg"),
    ("Belarus", "Minsk"),
    ("Kazakhstan", "Almaty"),
    ("Armenia", "Yerevan"),
    ("Georgia", "Tbilisi"),
)
CATEGORIES = (
    ("Food", "kg", True),
    ("Beverages", "l", True),
    ("Electronics", "pcs", False),
    ("Household", "pcs", False),
    ("Construction", "kg", False),
    ("Pharmaceuticals", "box", True),
)


def write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def generate(
    output_dir: Path,
    row_count: int,
    section_count: int,
    delivery_count: int,
    seed: int,
) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date(2026, 9, 4)

    suppliers: list[tuple[object, ...]] = []
    for supplier_id in range(1, row_count + 1):
        country, city = rng.choice(COUNTRIES_AND_CITIES)
        suppliers.append(
            (
                f"Supplier {supplier_id:04d}",
                f"{7700000000 + supplier_id:010d}",
                country,
                city,
                f"contact{supplier_id}@supplier.example",
                f"+7{9000000000 + supplier_id:010d}",
                f"{rng.uniform(1, 5):.2f}",
                rng.random() > 0.04,
                today - timedelta(days=rng.randint(30, 3650)),
            )
        )

    products: list[tuple[object, ...]] = []
    perishable_product_ids: set[int] = set()
    for product_id in range(1, row_count + 1):
        category, unit, is_perishable = rng.choice(CATEGORIES)
        if is_perishable:
            perishable_product_ids.add(product_id)
        products.append(
            (
                f"SKU-{product_id:06d}",
                f"{category} product {product_id:04d}",
                category,
                unit,
                f"{rng.uniform(25, 50000):.2f}",
                f"{rng.uniform(0.05, 250):.3f}",
                is_perishable,
                today - timedelta(days=rng.randint(0, 1825)),
            )
        )

    warehouses: list[tuple[object, ...]] = []
    for warehouse_id in range(1, row_count + 1):
        country, city = rng.choice(COUNTRIES_AND_CITIES)
        warehouses.append(
            (
                f"WH-{warehouse_id:05d}",
                f"Distribution center {warehouse_id:04d}",
                country,
                city,
                f"Industrial street, building {warehouse_id}",
                today - timedelta(days=rng.randint(180, 7300)),
            )
        )

    section_types = ("receiving", "storage", "cold_storage", "packing", "dispatch")
    sections_by_warehouse: dict[int, list[int]] = {
        warehouse_id: [] for warehouse_id in range(1, row_count + 1)
    }
    warehouse_sections: list[tuple[object, ...]] = []
    for section_id in range(1, section_count + 1):
        if section_id <= row_count:
            warehouse_id = section_id
            parent_section_id: int | str = ""
        else:
            warehouse_id = rng.randint(1, row_count)
            parent_section_id = rng.choice(sections_by_warehouse[warehouse_id])
        sections_by_warehouse[warehouse_id].append(section_id)
        warehouse_sections.append(
            (
                warehouse_id,
                parent_section_id,
                f"SEC-{warehouse_id:05d}-{section_id:06d}",
                f"Warehouse {warehouse_id:04d} section {section_id:06d}",
                rng.choice(section_types),
                f"{rng.uniform(20, 1500):.2f}",
                rng.randint(0, 8),
                rng.random() > 0.03,
            )
        )

    deliveries: list[tuple[object, ...]] = []
    base_timestamp = datetime(2025, 1, 1, 8, 0, 0)
    statuses = ("accepted", "accepted", "accepted", "inspection", "rejected")
    for delivery_id in range(1, delivery_count + 1):
        supplier_id = rng.randint(1, row_count)
        product_id = rng.randint(1, row_count)
        warehouse_id = rng.randint(1, row_count)
        delivered_at = base_timestamp + timedelta(
            days=rng.randint(0, 610), minutes=rng.randint(0, 1439)
        )
        expires_on = ""
        if product_id in perishable_product_ids:
            expires_on = (delivered_at.date() + timedelta(days=rng.randint(14, 730))).isoformat()
        deliveries.append(
            (
                supplier_id,
                product_id,
                warehouse_id,
                delivered_at.isoformat(sep=" "),
                rng.randint(1, 5000),
                f"{rng.uniform(10, 45000):.2f}",
                f"B-{delivery_id:08d}",
                rng.choice(statuses),
                expires_on,
            )
        )

    write_csv(
        output_dir / "suppliers.csv",
        ("name", "tax_id", "country", "city", "email", "phone", "rating", "is_active", "created_at"),
        suppliers,
    )
    write_csv(
        output_dir / "products.csv",
        ("sku", "name", "category", "unit", "unit_price", "weight_kg", "is_perishable", "created_at"),
        products,
    )
    write_csv(
        output_dir / "warehouses.csv",
        ("code", "name", "country", "city", "address", "opened_on"),
        warehouses,
    )
    write_csv(
        output_dir / "warehouse_sections.csv",
        ("warehouse_id", "parent_section_id", "code", "name", "section_type", "capacity_m3", "floor", "is_active"),
        warehouse_sections,
    )
    write_csv(
        output_dir / "deliveries.csv",
        ("supplier_id", "product_id", "warehouse_id", "delivered_at", "quantity", "unit_cost", "batch_number", "quality_status", "expires_on"),
        deliveries,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--sections", type=int, default=3000)
    parser.add_argument("--deliveries", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260904)
    args = parser.parse_args()
    generate(args.output_dir, args.rows, args.sections, args.deliveries, args.seed)
    print(
        f"Generated {args.rows} suppliers, products and warehouses, "
        f"{args.sections} warehouse sections and {args.deliveries} deliveries "
        f"in {args.output_dir}"
    )


if __name__ == "__main__":
    main()
