# RFC: реализация лабораторной работы № 5 с JSONB

## Статус

Предлагается к реализации.

Основание: [задание лабораторной работы](task.pdf).

## 1. Контекст

Лабораторная работа выполняется поверх PostgreSQL 17 и базы `supply_lab` из
`lr1`. В качестве формата обмена выбран JSON, а внутри PostgreSQL - тип
`jsonb`. XML не используется, поэтому проверка вариантов `FOR XML` из задания
для MSSQL к этой реализации неприменима.

Работа должна продемонстрировать полный цикл: выгрузку реляционной таблицы в
файл, обратную загрузку без потери данных, хранение вложенного документа и пять
основных операций над JSONB.

## 2. Ограничения и принятые решения

- DDL, запросы к JSONB и автоматические проверки выполняются через `psql`.
- Python 3 и `psycopg` используются только для потоковой работы с локальным
  JSON-файлом и управления транзакцией импорта/экспорта.
- ORM, pandas и внешние ETL-инструменты не используются.
- Все новые объекты создаются в схеме `lr5`; таблицы `public` не изменяются.
- Обменный формат - UTF-8 JSON Lines: одна самостоятельная JSON-запись на
  строку. Это позволяет обрабатывать файл потоково и не держать все поставки в
  памяти.
- Значения передаются в SQL параметрами. Имена таблиц и столбцов не принимаются
  из командной строки и не конкатенируются в запросы.
- Импорт является атомарным: при одной некорректной записи целевая таблица не
  меняется.

## 3. Объекты базы данных

### 3.1. Таблица `lr5.deliveries_imported`

Таблица создаётся на основе структуры `public.deliveries`:

```sql
CREATE TABLE lr5.deliveries_imported
    (LIKE public.deliveries INCLUDING ALL);
```

После `LIKE` добавляются внешние ключи на `public.suppliers`,
`public.products` и `public.warehouses`, поскольку PostgreSQL не копирует
внешние ключи конструкцией `LIKE`. Набор и типы десяти прикладных колонок
должны полностью совпадать с `public.deliveries`.

Таблица служит только результатом обратной загрузки. Перед импортом она
очищается внутри той же транзакции, после чего получает значения
`delivery_id` из файла. Идентичность исходной и загруженной таблиц проверяется
двумя направленными операциями `EXCEPT`.

### 3.2. Таблица `lr5.delivery_documents`

Для демонстрации вложенного JSON создаётся отдельная таблица:

```sql
CREATE TABLE lr5.delivery_documents (
    delivery_id bigint PRIMARY KEY
        REFERENCES public.deliveries (delivery_id),
    document jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT delivery_document_object_ck
        CHECK (jsonb_typeof(document) = 'object')
);
```

Одна строка содержит правдоподобный снимок поставки следующей формы:

```json
{
  "delivery_id": 1,
  "delivered_at": "2026-01-10T12:00:00",
  "supplier": {"id": 1, "tax_id": "770000000001", "name": "Поставщик"},
  "product": {"id": 1, "sku": "SKU-000001", "name": "Товар"},
  "warehouse": {"id": 1, "code": "WH-0001", "name": "Склад"},
  "batch": {
    "number": "BATCH-001",
    "quantity": 25,
    "unit_cost": 110.50,
    "total_cost": 2762.50
  },
  "quality": {
    "status": "accepted",
    "checks": ["documents", "quantity", "packaging"]
  },
  "expires_on": null
}
```

Документы формируются одним `INSERT ... SELECT` с `jsonb_build_object` и
соединениями исходных таблиц. Для повторного запуска используется
`ON CONFLICT (delivery_id) DO UPDATE`.

## 4. Экспорт и импорт

### 4.1. Экспорт

Сценарий `export_deliveries.py` открывает соединение с `supply_lab` и
потоково выполняет серверный запрос:

```sql
COPY (
    SELECT to_jsonb(d)::text
    FROM public.deliveries AS d
    ORDER BY d.delivery_id
) TO STDOUT;
```

Результат записывается во временный файл, закрывается и атомарно
переименовывается в `lr5/data/deliveries.jsonl`. Таким образом, при ошибке не
остаётся частично сформированного итогового файла. Python не преобразует типы
и не строит JSON вручную: сериализация выполняется PostgreSQL.

### 4.2. Импорт

Сценарий `import_deliveries.py` выполняет одну транзакцию:

1. Создаёт временную таблицу `raw_delivery_json(payload jsonb)`.
2. Потоково передаёт строки файла в неё через `COPY FROM STDIN`.
3. Проверяет, что каждая строка является JSON-объектом и содержит все десять
   обязательных ключей исходной таблицы.
4. Очищает `lr5.deliveries_imported`.
5. Преобразует записи на стороне PostgreSQL через
   `jsonb_to_record(payload)` с явно заданными именами и типами колонок.
6. Вставляет результат в `lr5.deliveries_imported`.
7. Сравнивает число строк и два множества через `EXCEPT`; несовпадение
   приводит к исключению и откату.

Прямое формирование `INSERT` для каждой строки не применяется. JSON
разбирается сервером, а `COPY` исключает лишние сетевые round-trip.

## 5. Обязательные операции над JSONB

Все примеры находятся в `lr5/sql/02_json_operations.sql` и работают с
`lr5.delivery_documents`.

### 5.1. Извлечение фрагмента

Оператор `->` возвращает вложенный объект без преобразования в текст:

```sql
SELECT delivery_id, document -> 'product' AS product
FROM lr5.delivery_documents;
```

### 5.2. Извлечение конкретного значения

Оператор `#>>` извлекает значение по пути как текст:

```sql
SELECT delivery_id, document #>> '{supplier,name}' AS supplier_name
FROM lr5.delivery_documents;
```

### 5.3. Проверка существования узла

Проверяются наличие верхнеуровневого ключа и вложенного массива:

```sql
SELECT delivery_id,
       document ? 'expires_on' AS has_expiration_key,
       document @? '$.quality.checks[*]' AS has_quality_checks
FROM lr5.delivery_documents;
```

### 5.4. Изменение документа

`jsonb_set` добавляет проверяющего в объект `quality`, не перезаписывая другие
поля. Операция демонстрируется внутри тестовой транзакции:

```sql
UPDATE lr5.delivery_documents
SET document = jsonb_set(
        document,
        '{quality,reviewed_by}',
        to_jsonb('lr5-demo'::text),
        true
    ),
    updated_at = clock_timestamp()
WHERE delivery_id = :test_delivery_id;
```

### 5.5. Разделение документа на строки

Элементы массива проверок разворачиваются в отдельные строки:

```sql
SELECT d.delivery_id, c.check_name
FROM lr5.delivery_documents AS d
CROSS JOIN LATERAL jsonb_array_elements_text(
    d.document #> '{quality,checks}'
) AS c(check_name);
```

## 6. Структура реализации

```text
lr5/
├── README.md
├── data/
│   └── .gitkeep
├── docs/
│   ├── RFC.md
│   └── task.pdf
├── requirements.txt
├── sql/
│   ├── install.sql
│   ├── 00_schema.sql
│   ├── 01_build_documents.sql
│   ├── 02_json_operations.sql
│   └── uninstall.sql
├── src/
│   ├── db.py
│   ├── export_deliveries.py
│   └── import_deliveries.py
└── tests/
    ├── test_json_operations.sql
    └── test_roundtrip.py
```

`install.sql` подключает SQL-файлы через `\ir`. Каждый SQL-сценарий начинается
с `\set ON_ERROR_STOP on`. Параметры соединения читаются стандартно из
`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` и `PGPASSWORD`.

## 7. Порядок запуска

```bash
psql -X -v ON_ERROR_STOP=1 -d supply_lab -f lr5/sql/install.sql
python3 lr5/src/export_deliveries.py
python3 lr5/src/import_deliveries.py
psql -X -v ON_ERROR_STOP=1 -d supply_lab \
  -f lr5/tests/test_json_operations.sql
python3 -m unittest lr5/tests/test_roundtrip.py
```

Повторный экспорт заменяет файл атомарно, повторный импорт полностью
пересобирает копию в одной транзакции, а повторная установка не создаёт
дубликатов документов.

## 8. Проверки

| Требование | Автоматическая проверка |
| --- | --- |
| Выгрузка таблицы в JSON | число непустых строк файла равно `count(*)` в `public.deliveries`; каждая строка разбирается как объект |
| Обратная загрузка | оба выражения `public.deliveries EXCEPT lr5.deliveries_imported` и обратное возвращают 0 строк |
| JSONB-атрибут | у каждой исходной поставки есть один объект с корректными идентификаторами и рассчитанной стоимостью |
| Извлечение фрагмента | `document -> 'product'` имеет тип `object` |
| Извлечение значения | имя поставщика совпадает с `public.suppliers.name` |
| Проверка существования | обязательные ключи найдены, заведомо отсутствующий путь даёт `false` |
| Изменение документа | добавлен только `quality.reviewed_by`, остальные поля сохранены |
| Разделение на строки | число строк равно сумме длин массивов `quality.checks` |
| Ошибочный файл | неверный JSON или отсутствующий ключ приводит к откату всего импорта |

Изменяющий JSON SQL-тест начинается с `BEGIN` и завершается `ROLLBACK`.
Python-тест импорта использует заранее сохранённое число строк и удаляет
только созданные им временные файлы.

## 9. Критерии готовности

1. Экспорт создаёт валидный UTF-8 JSONL без Python-сериализации записей.
2. Импорт восстанавливает точную реляционную копию `public.deliveries`.
3. В `lr5.delivery_documents` находятся правдоподобные вложенные документы.
4. Реализованы и проверены все пять требуемых операций над JSONB.
5. Неверный файл не приводит к частичной загрузке.
6. Сценарии допускают повторный запуск и не изменяют данные `lr1`.

