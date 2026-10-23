# Краткий справочник по конструкциям ЛР 5

## Создание JSONB

`to_jsonb(value)` преобразует значение или строку таблицы в `jsonb`:

```sql
SELECT to_jsonb(d)
FROM public.deliveries AS d;
```

`jsonb_build_object` создаёт объект, а `jsonb_build_array` - массив:

```sql
SELECT jsonb_build_object(
    'status', d.quality_status,
    'checks', jsonb_build_array('documents', 'quantity', 'packaging')
)
FROM public.deliveries AS d;
```

## Чтение JSONB

| Конструкция | Результат | Пример |
| --- | --- | --- |
| `->` | поле как JSONB | `document -> 'product'` |
| `->>` | поле как текст | `document ->> 'delivery_id'` |
| `#>` | значение по пути как JSONB | `document #> '{quality,checks}'` |
| `#>>` | значение по пути как текст | `document #>> '{supplier,name}'` |

Текстовый результат можно привести к нужному SQL-типу:

```sql
(document #>> '{batch,quantity}')::integer
```

## Проверка структуры JSONB

`jsonb_typeof` возвращает тип JSON-значения: `object`, `array`, `string`,
`number`, `boolean` или `null`.

```sql
jsonb_typeof(document) = 'object'
```

Операторы существования:

```sql
document ? 'expires_on'                 -- существует один ключ
document ?& ARRAY['delivery_id', 'product'] -- существуют все ключи
document @? '$.quality.checks[*]'       -- существует значение по JSONPath
```

## Изменение JSONB

`jsonb_set` записывает значение по указанному пути. Последний аргумент `true`
разрешает создать отсутствующий ключ:

```sql
jsonb_set(
    document,
    '{quality,reviewed_by}',
    to_jsonb('lr5-demo'::text),
    true
)
```

Оператор `#-` удаляет значение по пути. В тесте он используется для проверки,
что после обновления остальные части документа не изменились:

```sql
document #- '{quality,reviewed_by}'
```

## Преобразование JSONB в строки и столбцы

`jsonb_array_elements_text` разворачивает массив в набор строк. `LATERAL`
позволяет функции обращаться к документу текущей строки таблицы:

```sql
SELECT d.delivery_id, item.check_name
FROM lr5.delivery_documents AS d
CROSS JOIN LATERAL jsonb_array_elements_text(
    d.document #> '{quality,checks}'
) AS item(check_name);
```

`jsonb_to_record` раскладывает объект по явно заданным SQL-столбцам:

```sql
SELECT record.delivery_id, record.quantity
FROM raw_delivery_json AS raw
CROSS JOIN LATERAL jsonb_to_record(raw.payload) AS record(
    delivery_id bigint,
    quantity integer
);
```

## Таблицы и ограничения

`LIKE ... INCLUDING ALL` копирует столбцы, типы, значения по умолчанию,
`IDENTITY`, проверки и индексы исходной таблицы:

```sql
CREATE TABLE lr5.deliveries_imported
    (LIKE public.deliveries INCLUDING ALL);
```

Внешние ключи эта конструкция не копирует, поэтому они добавляются отдельно
через `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`.

`ON CONFLICT ... DO UPDATE` делает повторное построение документов безопасным:

```sql
ON CONFLICT (delivery_id) DO UPDATE
SET document = EXCLUDED.document;
```

## Экспорт, импорт и проверка равенства

`COPY ... TO STDOUT` потоково выгружает результат запроса, а
`COPY ... FROM STDIN` потоково загружает записи без отдельного `INSERT` для
каждой строки.

Две таблицы сравниваются в обоих направлениях оператором `EXCEPT`:

```sql
SELECT * FROM public.deliveries
EXCEPT
SELECT * FROM lr5.deliveries_imported;
```

Пустой результат в обоих направлениях означает полное равенство множеств.

Временная таблица существует только в текущем соединении:

```sql
CREATE TEMP TABLE raw_delivery_json (
    payload jsonb NOT NULL
) ON COMMIT DROP;
```

Импорт выполняется в одной транзакции. При ошибке PostgreSQL делает `ROLLBACK`,
поэтому частично загруженные данные не сохраняются. В демонстрации изменения
JSONB связка `BEGIN` и `ROLLBACK` позволяет показать обновление без изменения
итогового состояния базы.

## Команды psql

| Команда | Назначение |
| --- | --- |
| `\set ON_ERROR_STOP on` | остановить сценарий при первой ошибке |
| `\ir file.sql` | подключить файл относительно текущего сценария |
| `\gset` | сохранить результат запроса в переменные psql |
| `\if ... \else ... \endif` | выполнить условную проверку в сценарии |

В Python значения передаются в запросы параметрами `%s` или именованными
параметрами `%(name)s`. Это отделяет данные от текста SQL. Контекстные
менеджеры Psycopg закрывают ресурсы и автоматически фиксируют успешную
транзакцию либо откатывают её при исключении.
