# Лабораторная работа № 7

Реализация [RFC](docs/RFC.md) на Python 3.11+, SQLAlchemy 2.0 и Psycopg 3.
Используется существующая PostgreSQL 17 `supply_lab` из `../lr1`.

## Подготовка

База должна содержать таблицы и данные ЛР 1, а также процедуру
`public.sp_describe_table` из `../lr3/queries/02_procedures.sql`.
Не запускайте повторно сценарий создания таблиц ЛР 1 над готовой базой:
он удаляет исходные таблицы.

Все команды ниже выполняются из каталога `lr7`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

export PGHOST=127.0.0.1 PGPORT=55432 PGDATABASE=supply_lab
export PGUSER=postgres PGPASSWORD=postgres
psql -X -v ON_ERROR_STOP=1 -f sql/install.sql
```

Указанные параметры подключения используются и по умолчанию. Спецсимволы
в пароле поддерживаются через `sqlalchemy.URL.create`. Для SQL-диагностики
задайте `LR7_SQL_ECHO=1`; по умолчанию SQL не выводится.

Если используется контейнер ЛР 1 и локальный `psql` не установлен:

```bash
podman exec -i lr1-postgres psql -X -v ON_ERROR_STOP=1 \
  -U postgres -d supply_lab < sql/install.sql
```

Установка создаёт только схему `lr7` и таблицу `lr7.delivery_tags` и допускает
повторный запуск. ORM не создаёт и не меняет таблицы `public`.

## Демонстрация

```bash
python -m src.demo
```

Запуск из родительского каталога `db`:

```bash
lr7/.venv/bin/python -m lr7.src.demo
```

Демонстрация выполняет пять запросов к объектам, экспортирует поставки
в `data/deliveries.json`, читает JSON и показывает обновление и добавление
в отдельном файле `data/deliveries.edited.json`. Можно указать путь экспорта:

```bash
python -m src.demo --json-path data/example.json
```

Далее выполняются однотабличная и многотабличная SQL-выборки, цикл
INSERT → UPDATE → DELETE тега и вызов процедуры описания `deliveries`.
Вывод больших выборок ограничен первыми пятью строками.
При пустых исходных таблицах операции, требующие существующую строку,
пропускаются. Для полной демонстрации нужны загруженные данные ЛР 1.

Все операции демонстрации с БД находятся во внешней транзакции с итоговым
откатом, в том числе при исключении. Тестовые строки не сохраняются;
PostgreSQL sequences могут получать пропуски, поскольку `nextval` не откатывается.
JSON-файлы остаются на диске; повторный запуск перезаписывает их.

## Модули и контракты

- `src/models.py`: полное отображение `Supplier`, `Product`, `Warehouse`,
  `Delivery`, `DeliveryTag`; отношения поставки не выполняют неявных запросов.
- `src/object_queries.py`: фильтрация активных поставщиков по рейтингу,
  сортировка товаров по цене и SKU, агрегаты поставок по статусу, соединение
  со складами и проверка `any`/`all`. Функции работают с обычными объектами,
  включая dataclass, и не изменяют входные коллекции. Запрос с кванторами
  возвращает поставщика и признак `has_rejected`; поставщики без поставок
  и с неположительным количеством исключаются.
- `src/json_queries.py`: `export_json(sessions, path)` выполняет один
  SELECT с тремя JOIN. Поле `tags` экспортируется пустым и предназначено для
  локальных тегов документа. `read_json(path, status)` возвращает ID,
  название поставщика и товара, код склада, количество и стоимость `Decimal`.
  `update_json` изменяет статус одной поставки; `append_json` добавляет
  уникальный ID с обязательными полями. Допустимы `accepted`, `inspection`,
  `rejected`. Стоимость хранится десятичной строкой, время формирования — UTC.
  Ошибки валидации дают `ValueError`, ошибки файловой системы — `OSError`.
  Запись идёт через временный файл, повторное чтение и `os.replace`.
  Ошибка сохраняет исходные байты и удаляет временный файл. Атомарная замена
  рассчитана на одного писателя; блокировок для конкурирующих изменений нет.
- `src/repository.py`: `Repository(sessions)` предоставляет методы из RFC.
  Даты фильтруются по полуинтервалу `[date_from, date_to)`, цена — включительно.
  DML использует `RETURNING` и `scalar_one()`: отсутствие строки вызывает
  `NoResultFound`, несколько строк — `MultipleResultsFound`.
  Ограничения БД, включая уникальность тега, дают `IntegrityError` с откатом.
  `describe_table_via_procedure("deliveries")` выполняет один параметризованный
  `CALL`, без предварительного SELECT. Возвращается словарь метаданных.
- `src/db.py`: фабрика сеансов с `autoflush=False`, `expire_on_commit=False`,
  `autobegin=False`; методы явно используют `Session.begin()`.

Пример самостоятельного вызова репозитория:

```python
from src.db import make_engine, make_session_factory
from src.repository import Repository

engine = make_engine()
try:
    repository = Repository(make_session_factory(engine))
    metadata = repository.describe_table_via_procedure("deliveries")
    print(metadata["columns"])
finally:
    engine.dispose()
```

## Тесты

Модульные тесты без подключения к БД:

```bash
python -m unittest discover -s tests -v
```

Все тесты, включая интеграционные на существующей PostgreSQL:

```bash
LR7_INTEGRATION=1 python -m unittest discover -s tests -v
```

Из каталога `db`:

```bash
LR7_INTEGRATION=1 lr7/.venv/bin/python -m unittest discover -s lr7/tests -v
```

Интеграционные тесты требуют установленную таблицу тегов, процедуру ЛР 3
и хотя бы одну поставку с соответствующими справочниками. При явном включении
интеграционных тестов недоступность БД является ошибкой, а не пропуском.
Проверяются соответствие моделей живой схеме, связанные параметры SQL,
полуинтервал дат, DML и откат дубликатов, единственный CALL, один SELECT
при экспорте и отсутствие DDL при импорте моделей.

Каждый интеграционный тест работает во внешней транзакции с итоговым откатом.
Сеансы используют SAVEPOINT через `join_transaction_mode="create_savepoint"`
по [документации SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites).

## Удаление таблицы ЛР 7

```bash
psql -X -v ON_ERROR_STOP=1 -f sql/uninstall.sql
```

Удаляются таблица тегов и пустая схема `lr7`. Сценарий не использует `CASCADE`:
если в схеме есть другие объекты или зависимости, транзакция откатывается.
