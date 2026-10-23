import argparse
import copy
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from . import object_queries
from .db import make_engine, make_session_factory
from .json_queries import append_json, export_json, json_default, read_json, update_json
from .repository import Repository


def show(label: str, value: object) -> None:
    print(f"\n{label}")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=json_default))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-path",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "deliveries.json",
    )
    args = parser.parse_args()
    engine = make_engine()
    try:
        # Внешняя транзакция откатывает DML даже при ошибке позднее в демонстрации.
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                sessions = make_session_factory(connection)
                repository = Repository(sessions)
                data = repository.load_collections()
                suppliers = data["suppliers"]
                products = data["products"]
                deliveries = data["deliveries"]
                show(
                    "1. Активные поставщики (первые 5)",
                    object_queries.select_active_suppliers(suppliers, Decimal(4))[:5],
                )
                show(
                    "2. Дорогие товары",
                    [
                        {"sku": product.sku, "unit_price": product.unit_price}
                        for product in object_queries.top_products(products, 5)
                    ],
                )
                show(
                    "3. Группировка поставок",
                    object_queries.summarize_deliveries(deliveries),
                )
                show(
                    "4. Соединение со складами (первые 5)",
                    object_queries.join_deliveries_warehouses(
                        deliveries, data["warehouses"]
                    )[:5],
                )
                show(
                    "5. ANY / ALL (первые 5)",
                    [
                        {
                            "tax_id": row["supplier"].tax_id,
                            "has_rejected": row["has_rejected"],
                        }
                        for row in object_queries.suppliers_with_valid_deliveries(
                            suppliers, deliveries
                        )[:5]
                    ],
                )
                document = export_json(sessions, args.json_path)
                show(
                    "JSON: принятые поставки (первые 5)",
                    read_json(args.json_path, "accepted")[:5],
                )
                if document["deliveries"]:
                    # Изменяем отдельный файл, сохраняя исходный экспорт для сравнения.
                    edited_path = args.json_path.with_name(
                        f"{args.json_path.stem}.edited.json"
                    )
                    edited_path.write_bytes(args.json_path.read_bytes())
                    first = document["deliveries"][0]
                    new_status = (
                        "inspection"
                        if first["quality_status"] != "inspection"
                        else "accepted"
                    )
                    update_json(edited_path, first["delivery_id"], new_status)
                    extra = copy.deepcopy(first)
                    extra["delivery_id"] = (
                        max(row["delivery_id"] for row in document["deliveries"]) + 1
                    )
                    extra["tags"] = ["json-demo"]
                    append_json(edited_path, extra)
                    print(f"JSON update/append: {edited_path}")
                if products:
                    show(
                        "SQL: товары выбранной категории",
                        [
                            {"sku": product.sku, "unit_price": product.unit_price}
                            for product in repository.select_products(
                                products[0].category, Decimal(0), 5
                            )
                        ],
                    )
                start = min(
                    (delivery.delivered_at for delivery in deliveries),
                    # delivered_at в lr1 имеет тип timestamp without time zone.
                    default=datetime(2026, 1, 1),  # noqa: DTZ001
                )
                show(
                    "SQL: соединение за первые сутки (первые 5)",
                    repository.select_delivery_details(
                        start, start + timedelta(days=1)
                    )[:5],
                )
                if deliveries:
                    tag_id = repository.insert_delivery_tag(
                        deliveries[0].delivery_id, f"demo-{uuid4().hex}"
                    )
                    repository.rename_delivery_tag(tag_id, f"edit-{uuid4().hex}")
                    repository.delete_delivery_tag(tag_id)
                    show("SQL: INSERT → UPDATE → DELETE", {"tag_id": tag_id})
                show(
                    "CALL sp_describe_table",
                    repository.describe_table_via_procedure("deliveries"),
                )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
