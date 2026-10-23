"""CLI

to run: python3 -m lr6.src.cli или python3 -m src.cli
"""

from collections.abc import Collection
from datetime import date
import json
from typing import Any

import psycopg

from . import db, queries


def read_int(prompt: str, minimum: int = 1, maximum: int | None = None) -> int:
    while True:
        try:
            value = int(input(prompt))
            if value < minimum or (maximum is not None and value > maximum):
                raise ValueError
            return value
        except ValueError:
            upper = f" до {maximum}" if maximum is not None else ""
            print(f"Введите целое число от {minimum}{upper}.")


def read_date(prompt: str) -> date:
    while True:
        try:
            return date.fromisoformat(input(prompt).strip())
        except ValueError:
            print("Введите дату в формате ГГГГ-ММ-ДД.")


def read_choice(prompt: str, choices: Collection[str]) -> str:
    while True:
        value = input(prompt).strip()
        if value in choices:
            return value
        print("Допустимые значения: " + ", ".join(sorted(choices)))


def read_non_empty_text(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Текст не должен быть пустым.")


def print_table(result: queries.TableResult) -> None:
    columns, rows = result
    if not rows:
        print("Строки не найдены.")
        return
    # Экранируем переводы строк и табуляции, чтобы не ломать таблицу.
    values = [
        [
            "NULL" if cell is None else str(cell).replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            for cell in row
        ]
        for row in rows
    ]
    widths = [max(len(name), *(len(row[i]) for row in values)) for i, name in enumerate(columns)]
    print(" | ".join(name.ljust(width) for name, width in zip(columns, widths)))
    print("-+-".join("-" * width for width in widths))
    for row in values:
        print(" | ".join(cell.ljust(width) for cell, width in zip(row, widths)))


MENU = """
1. Число поставок по статусу
2. Последние поставки (JOIN)
3. Рейтинг поставщиков (CTE и оконные функции)
4. Метаданные столбцов
5. Стоимость поставки (скалярная функция ЛР3)
6. Поставки поставщика (табличная функция ЛР3)
7. Описание таблицы (процедура ЛР3)
8. Информация о сервере
9. Создать таблицу заметок
10. Добавить заметку
0. Выход
"""


def execute_command(connection: psycopg.Connection[tuple[Any, ...]], command: str) -> None:
    if command == "1":
        status = read_choice("Статус: ", queries.STATUSES)
        print(queries.show_delivery_count_by_status(connection, status))
    elif command == "2":
        print_table(queries.show_recent_deliveries(connection, read_int("Лимит (1–100): ", maximum=100)))
    elif command == "3":
        start = read_date("Начало периода: ")
        end = read_date("Конец периода (не включительно): ")
        print_table(queries.show_supplier_cost_rating(connection, start, end))
    elif command == "4":
        table = read_choice("Таблица: ", queries.TABLES)
        print_table(queries.describe_columns(connection, table))
    elif command == "5":
        print(queries.show_delivery_total(connection, read_int("ID поставки: ")))
    elif command == "6":
        print_table(queries.show_supplier_deliveries(connection, read_int("ID поставщика: ")))
    elif command == "7":
        table = read_choice("Таблица: ", queries.TABLES)
        print(json.dumps(queries.describe_table_with_procedure(connection, table), ensure_ascii=False, indent=2))
    elif command == "8":
        print_table(queries.show_server_info(connection))
    elif command == "9":
        queries.create_delivery_notes_table(connection)
        print("Таблица lr6.delivery_notes готова.")
    elif command == "10":
        delivery_id = read_int("ID поставки: ")
        text = read_non_empty_text("Заметка: ")
        print_table(queries.add_delivery_note(connection, delivery_id, text))


def run_menu(connection: psycopg.Connection[tuple[Any, ...]]) -> None:
    while True:
        print(MENU)
        command = read_choice("Пункт меню: ", {str(i) for i in range(11)})
        if command == "0":
            return
        try:
            execute_command(connection, command)
        except ValueError as error:
            print(error)
        except psycopg.IntegrityError as error:
            print(f"Нарушение ограничений: {error}")
        except psycopg.errors.UndefinedFunction as error:
            print(f"Установите функции и процедуры ЛР3: {error}")
        except psycopg.errors.UndefinedTable as error:
            if command == "10":
                print("Сначала создайте таблицу заметок: пункт 9.")
            else:
                print(f"Отсутствует таблица: {error}")
        except psycopg.OperationalError as error:
            print(f"Соединение потеряно: {error}")
            return
        except psycopg.Error as error:
            print(f"Ошибка PostgreSQL: {error}")


def main() -> int:
    try:
        with db.connect() as connection:
            run_menu(connection)
    except (EOFError, KeyboardInterrupt):
        print("\nРабота завершена.")
        return 0
    except (psycopg.Error, ValueError) as error:
        print(f"Не удалось открыть базу: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
