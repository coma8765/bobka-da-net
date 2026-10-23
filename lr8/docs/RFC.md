# RFC: ETL-загрузка файлов в PostgreSQL через NiFi для ЛР № 8

## Статус

Реализовано; инструкции запуска и фактические уточнения: [nifi-flow.md](nifi-flow.md).

Основание: [задание лабораторной работы](task.pdf).

## 1. Контекст

Лабораторная работа требует приложение-генератор файлов и ETL-процесс,
который регулярно загружает новые записи в базу, валидирует вход и ведёт
журнал обработки. Целевая база - PostgreSQL 17 `supply_lab`.

В соответствии с заданием ETL-процесс строится на Apache NiFi 2.x. Apache Airflow не используется ни как оркестратор, ни как планировщик.
Прикладной код ограничен базовым Python 3, SQL разворачивается через `psql`.

## 2. Архитектура потока

```text
Python generator --каждые 5 минут--> inbox/*.json
                                      |
                                      v
                 GetFile -> имя -> whole-file check -> ValidateRecord -> ConvertRecord
                                      | invalid
                                      v
                                   rejected/
                                      |
                                      v valid
                 SplitJson -> MergeContent -> PutDatabaseRecord
                                      |             |
                    failure -> rejected/            +--> PostgreSQL
                                      |                  lr8.delivery_events
                                      v success
                               LogAttribute -> archive/ + receipt
```

NiFi отвечает только за обнаружение, проверку, преобразование, загрузку,
маршрутизацию и журналирование. Генератор не подключается к базе и не считает
файл загруженным самостоятельно.

## 3. Формат входного файла

Выбран JSON-массив. Каждый файл содержит от 1 до 20 только новых событий
приёмки поставки; команды обновления и удаления в формате отсутствуют.

Маска имени:

```text
<file_id>__delivery_events__<formed_at>.json
```

Пример:

```text
550e8400-e29b-41d4-a716-446655440000__delivery_events__20260912T120000Z.json
```

Маска включает все элементы задания:

- `file_id` - UUID файла;
- `delivery_events` - имя целевой таблицы;
- `formed_at` - момент формирования в UTC.

Одна запись имеет вид:

```json
{
  "event_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "source_file_id": "550e8400-e29b-41d4-a716-446655440000",
  "supplier_tax_id": "7700000001",
  "product_sku": "SKU-000001",
  "warehouse_code": "WH-00001",
  "delivered_at": "2026-09-12T11:59:30Z",
  "quantity": 25,
  "unit_cost": 110.50,
  "batch_number": "ETL-20260912-0001",
  "quality_status": "accepted",
  "expires_on": null
}
```

`source_file_id` обязан совпадать с UUID в имени файла. `event_id` и
`batch_number` никогда не повторяются в новых файлах.

## 4. Python-генератор

`generator.py` использует только стандартную библиотеку: `argparse`, `json`,
`uuid`, `datetime`, `decimal`, `random`, `pathlib`, `time` и `os`.

Поддерживаются два режима:

```bash
python3 lr8/src/generator.py --once
python3 lr8/src/generator.py --watch --interval 300
```

В режиме `--watch` новый файл создаётся каждые 300 секунд. Для демонстрации и
тестов интервал можно уменьшить аргументом, но значение по умолчанию остаётся
равным пяти минутам.

Алгоритм одного цикла:

1. Создать `file_id`, UTC-время и от 1 до 20 событий.
2. Проверить сформированный объект теми же базовыми правилами, что ожидаются в
   NiFi.
3. Записать JSON во временный файл каталога `outbox`.
4. Выполнить `flush` и атомарно переместить готовый файл в `inbox` через
   `os.replace`.
5. Напечатать имя и число событий.

NiFi никогда не видит частично записанный файл. При перезапуске генератор не
трогает существующие файлы и создаёт новый UUID.

## 5. Целевая таблица PostgreSQL

### 5.1. События поставок

```sql
CREATE SCHEMA IF NOT EXISTS lr8;

CREATE TABLE IF NOT EXISTS lr8.delivery_events (
    event_id uuid PRIMARY KEY,
    source_file_id uuid NOT NULL,
    supplier_tax_id varchar(12) NOT NULL,
    product_sku varchar(20) NOT NULL,
    warehouse_code varchar(16) NOT NULL,
    delivered_at timestamp with time zone NOT NULL,
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_cost numeric(12, 2) NOT NULL CHECK (unit_cost > 0),
    batch_number varchar(40) NOT NULL UNIQUE,
    quality_status varchar(16) NOT NULL
        CHECK (quality_status IN ('accepted', 'inspection', 'rejected')),
    expires_on date,
    loaded_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_file_id, event_id)
);
```

Таблица сохраняет естественные идентификаторы из внешнего потока. Она не
вставляет строки напрямую в `public.deliveries`, поскольку входной файл может
содержать ещё не зарегистрированные справочные значения. Перенос из staging
в основную модель находится вне ЛР 8. Первичные и уникальные ключи делают
повторную обработку файла видимой ошибкой, а не незаметным дублем.

## 6. Controller Services NiFi

Для работы используется официальный дистрибутив или контейнер Apache NiFi
ветки 2.x. В `README.md` фиксируется реально проверенная patch-версия, порты и
bind mounts для `runtime`. Каталоги репозитория данных, FlowFile и provenance
NiFi размещаются на постоянном томе, чтобы перезапуск процесса не терял
очередь. Airflow и дополнительные планировщики не устанавливаются.

В Process Group `lr8-delivery-import` создаются:

- `JsonTreeReader` со схемой входной записи;
- `JsonRecordSetWriter` для канонического JSON;
- `DBCPConnectionPool` с PostgreSQL JDBC URL к `supply_lab`;

Секрет базы передаётся NiFi через sensitive property или переменную окружения
и не экспортируется в flow definition. Проверка соединения выполняется до
запуска процессоров.

## 7. Основной NiFi flow

### 7.1. Получение и имя файла

`GetFile` читает только `*.json` из `lr8/runtime/inbox`, не удаляет исходник до
успешного принятия FlowFile и работает с периодом опроса не более 30 секунд.

`RouteOnAttribute` принимает только имена по регулярному выражению:

```text
^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}__delivery_events__[0-9]{8}T[0-9]{6}Z\.json$
```

`UpdateAttribute` извлекает `file_id`, `table_name` и `formed_at`. Любое другое
имя идёт в ветку `invalid_filename`.

### 7.2. Валидация содержимого

Перед `ValidateRecord` процессор `ExecuteStreamCommand` запускает
`src/validate_file.py` на стандартном Python. Проверяется целый UTF-8 файл:
непустой массив из 1–20 записей, обязательные поля, типы, UUID, календарные даты,
числовые ограничения, допустимый статус, непустые ключи, совпадение
`source_file_id` с именем и уникальность событий/партий внутри файла.

Это уточнение необходимо: `ValidateRecord` сам по себе может разделить вход на
valid/invalid и не выдаёт FlowFile для пустого набора. Бизнес-проверка целого
файла заменяет `QueryRecord`, чтобы исключить частичную загрузку. Затем
`ValidateRecord` выполняет дополнительную проверку по Avro-схеме.

### 7.3. Преобразование и загрузка

`ConvertRecord` приводит корректный набор к каноническому JSON. `SplitJson` с
JSONPath `$[*]` демонстрирует разделение массива на записи, требуемое заданием.
Сразу после него `MergeContent` в режиме Defragment собирает все фрагменты
обратно в один массив по `fragment.identifier`. Это позволяет загрузить файл
одним `PutDatabaseRecord` и получить атомарный успех или отказ для всего
файла.

`PutDatabaseRecord` настроен так:

- Record Reader - `JsonTreeReader`;
- Statement Type - `INSERT`;
- Schema Name - `lr8`;
- Table Name - фиксированное `delivery_events`;
- транзакция - одна на входной FlowFile;
- неописанные колонки не добавляются автоматически.

Для NiFi 2.x именно `PutDatabaseRecord` заменяет связку
`ConvertJSONToSQL` + `PutSQL`, как разрешено заданием.

После успешной вставки устанавливается `load.status=committed`; после
сохранения архива и квитанции `LogAttribute` со статусом `loaded` пишет `file_id`, `filename`,
`record_count`, `fragment.identifier`, время и статус.

### 7.4. Успех и ошибки

Успешный исходный файл сохраняется `PutFile` в `runtime/archive/YYYY-MM-DD`.
Следующий шаг создаёт в `runtime/receipts` небольшой файл
`<source-name>.loaded.json` с идентификатором FlowFile, числом записей и
временем. Ошибочный файл сохраняется в `runtime/rejected`, а рядом создаётся
JSON с причиной, стадией, UUID FlowFile и временем.

Все failure/invalid/unmatched relationships подключены к ветке ошибки. Ни одна
relationship не auto-terminate без явного решения. Для очередей задаются
ограничения back pressure, чтобы остановка PostgreSQL не заполнила диск.

## 8. Журналирование и наблюдаемость

Требование журналирования выполняется на трёх уровнях:

- `LogAttribute` и Data Provenance NiFi позволяют проследить движение
  FlowFile и причину отказа;
- receipt-файл хранит компактный устойчивый результат обработки рядом с
  архивом;
- уникальные ключи `lr8.delivery_events` не позволяют повторно принять те же
  записи как новые.

Статус `loaded` создаётся только после вставки всех записей файла. Если запись
receipt не удалась, FlowFile остаётся в очереди повторной записи квитанции.
INSERT уже зафиксирован и повторно на этом пути не выполняется; итоговый
LogAttribute вызывается только после сохранения квитанции. В логах не выводятся пароль и полное
содержимое записей.

## 9. Структура реализации

```text
lr8/
├── README.md
├── docs/
│   ├── RFC.md
│   ├── nifi-flow.md
│   └── task.pdf
├── nifi/
│   ├── delivery-event.avsc
│   └── lr8-delivery-import.json
├── runtime/
│   ├── inbox/.gitkeep
│   ├── outbox/.gitkeep
│   ├── archive/.gitkeep
│   ├── receipts/.gitkeep
│   └── rejected/.gitkeep
├── sql/
│   ├── install.sql
│   └── uninstall.sql
├── src/
│   └── generator.py
└── tests/
    ├── test_generator.py
    ├── fixtures/
    │   ├── valid.json
    │   ├── invalid_schema.json
    │   └── invalid_values.json
    └── verify_database.sql
```

`lr8-delivery-import.json` - экспорт Process Group без чувствительных
параметров. `nifi-flow.md` содержит точные свойства процессоров, имена
relationships и порядок импорта.

## 10. Развертывание и демонстрация

1. Создать таблицы:

   ```bash
   psql -X -v ON_ERROR_STOP=1 -d supply_lab -f lr8/sql/install.sql
   ```

2. Запустить NiFi 2.x, настроить PostgreSQL JDBC и импортировать Process Group.
3. Запустить все Controller Services и процессоры.
4. Создать один файл:

   ```bash
   python3 lr8/src/generator.py --once
   ```

5. Убедиться, что файл перемещён в archive, записи появились в
   `lr8.delivery_events`, а в `runtime/receipts` создан результат загрузки.
6. Для демонстрации расписания запустить генератор с `--watch` и наблюдать не
   менее двух последовательных файлов.

## 11. Проверки

| Сценарий | Ожидаемый результат |
| --- | --- |
| Корректный файл | все записи вставлены, receipt создан, файл находится в archive |
| Неверная маска имени | записей нет, файл и описание ошибки находятся в rejected |
| Повреждённый JSON | whole-file проверка отклоняет весь файл |
| Нет обязательного поля | весь файл отклонён до PostgreSQL |
| Неверное количество/цена/статус | бизнес-валидация отклоняет весь файл |
| Несовпадение `source_file_id` | файл отклонён |
| Дубликат `event_id` внутри файла | файл отклонён |
| Повторная подача загруженного файла | ограничения БД не допускают дубли, событие отражено в NiFi |
| PostgreSQL недоступен | FlowFile остаётся в управляемой очереди/retry, данные не теряются |
| Два цикла по 5 минут | созданы и загружены два файла с разными UUID |

`test_generator.py` проверяет маску, уникальность идентификаторов, интервал по
умолчанию, атомарное появление файла и соответствие схеме. SQL-проверка
сверяет `count(*)`, уникальность ключей, ограничения и соответствие каждой
строки идентификатору исходного файла.

## 12. Критерии готовности

1. Генератор по умолчанию создаёт новый JSON-файл раз в пять минут.
2. Имя содержит идентификатор, имя таблицы и UTC-время формирования.
3. NiFi 2.x валидирует имя, структуру и бизнес-поля до вставки.
4. `PutDatabaseRecord` выполняет только `INSERT` и атомарно загружает файл.
5. Успешные и ошибочные файлы разнесены по archive/rejected и наблюдаемы в
   NiFi.
6. Каждый успешно загруженный файл имеет запись `LogAttribute`, provenance и
   один receipt-файл.
7. Apache Airflow отсутствует в зависимостях, конфигурации и инструкции.
