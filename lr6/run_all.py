import argparse
from collections.abc import Callable
from datetime import timedelta
import json
from typing import Any

import psycopg

from src import db, queries
from src.cli import print_table


def run_all(connection: psycopg.Connection[tuple[Any, ...]]) -> int:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT delivery_id, supplier_id, delivered_at::date
            FROM public.deliveries
            ORDER BY delivered_at DESC, delivery_id DESC
            LIMIT 1
        """)
        delivery = cursor.fetchone()
    if delivery is None:
        raise ValueError("В public.deliveries нет поставок. Загрузите данные ЛР1.")
    delivery_id, supplier_id, date_from = delivery
    date_to = date_from + timedelta(days=1)
    print(f"Поставка: {delivery_id}; поставщик: {supplier_id}")
    print(f"Период рейтинга: [{date_from}, {date_to}); статус: accepted; лимит: 5")

    operations: list[tuple[str, Callable[[], Any]]] = [
        ("Скалярный запрос", lambda: queries.show_delivery_count_by_status(connection, "accepted")),
        ("Запрос с несколькими JOIN", lambda: queries.show_recent_deliveries(connection, 5)),
        ("CTE и оконные функции", lambda: queries.show_supplier_cost_rating(connection, date_from, date_to)),
        ("Запрос к метаданным", lambda: queries.describe_columns(connection, "deliveries")),
        ("Вызов скалярной функции", lambda: queries.show_delivery_total(connection, delivery_id)),
        ("Вызов табличной функции", lambda: queries.show_supplier_deliveries(connection, supplier_id)),
        ("Вызов хранимой процедуры", lambda: queries.describe_table_with_procedure(connection, "deliveries")),
        ("Вызов системной функции", lambda: queries.show_server_info(connection)),
        ("Создание таблицы", lambda: queries.create_delivery_notes_table(connection)),
        (
            "Вставка данных",
            lambda: queries.add_delivery_note(connection, delivery_id, "Демонстрационная заметка ЛР6"),
        ),
    ]
    exit_code = 0
    for number, (title, operation) in enumerate(operations, start=1):
        print(f"\n{'=' * 20} Пункт {number}. {title} {'=' * 20}", flush=True)
        try:
            # В режиме --rollback это savepoint: ошибка не прерывает следующие пункты.
            with connection.transaction():
                result = operation()
            if number == 7:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif number == 9:
                print("Таблица lr6.delivery_notes готова.")
            elif number in (1, 5):
                print(result)
            else:
                print_table(result)
        except (psycopg.Error, ValueError) as error:
            print(f"Ошибка: {error}")
            exit_code = 1
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Запустить все 10 пунктов ЛР6 с выводом в stdout.")
    parser.add_argument("--rollback", action="store_true", help="Откатить изменения после демонстрации.")
    args = parser.parse_args()
    try:
        with db.connect() as connection:
            if args.rollback:
                with connection.transaction(force_rollback=True):
                    exit_code = run_all(connection)
                print("\nИзменения демонстрации отменены (ROLLBACK).")
                return exit_code
            return run_all(connection)
    except (psycopg.Error, ValueError) as error:
        print(f"Ошибка запуска: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nЗапуск прерван.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
