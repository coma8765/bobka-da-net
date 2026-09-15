# RFC: реализация лабораторной работы № 4 на PL/Python

Статус: реализовано и проверено на PostgreSQL 17.11.

Основание: [задание лабораторной работы](task.pdf).

## 1. Контекст

Задание лабораторной работы требует создать, развернуть и протестировать шесть
объектов, аналогичных объектам SQL CLR:

- определяемую пользователем скалярную функцию;
- пользовательскую агрегатную функцию;
- определяемую пользователем табличную функцию;
- хранимую процедуру;
- триггер;
- определяемый пользователем тип данных.

Реализация выполняется в PostgreSQL 17 поверх базы `supply_lab`, созданной в
первой лабораторной работе. Используются таблицы `public.suppliers`,
`public.products`, `public.warehouses` и `public.deliveries`.

## 2. Ограничения реализации

- Единственный клиент базы данных - `psql`.
- Единственный процедурный язык - Python через расширение `plpython3u`.
- Python-код хранится внутри SQL-файлов в dollar-quoted телах объектов
  `LANGUAGE plpython3u`.
- Внешнее Python-приложение, ORM, PL/pgSQL и компилируемые расширения не
  используются.
- Все объекты лабораторной работы создаются в отдельной схеме `lr4`.
- Все обращения к таблицам и функциям квалифицируются именем схемы.
- SQL с пользовательскими значениями выполняется через `plpy.prepare` и
  параметры. Конкатенация значений в SQL-строки запрещена.
- Процедура не выполняет `COMMIT` или `ROLLBACK`: границами транзакции управляет
  вызывающий сценарий `psql`.

`plpython3u` является недоверенным языком. Расширение устанавливается и функции
создаются ролью с правами суперпользователя. После установки право `EXECUTE`
выдаётся только роли, используемой для лабораторной работы.

## 3. Предварительные требования

На сервере PostgreSQL должен быть доступен пакет PL/Python для той же основной
версии сервера. Наличие расширения проверяется до развертывания:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name = 'plpython3u';
```

Отсутствие строки означает, что серверный пакет PL/Python не установлен.
Исправить это только SQL-командой через `psql` невозможно. После появления
расширения развертывание выполняет:

```sql
CREATE EXTENSION IF NOT EXISTS plpython3u;
CREATE SCHEMA IF NOT EXISTS lr4;
```

## 4. Решение

### 4.1. Скалярная функция `lr4.delivery_total`

Сигнатура:

```sql
CREATE OR REPLACE FUNCTION lr4.delivery_total(
    p_quantity integer,
    p_unit_cost numeric
)
RETURNS numeric
LANGUAGE plpython3u
IMMUTABLE
STRICT;
```

Функция вычисляет стоимость партии как `p_quantity * p_unit_cost` и округляет
результат до двух десятичных знаков по правилу `ROUND_HALF_UP` из стандартного
модуля Python `decimal`.

Правила:

- `p_quantity` должен быть больше нуля;
- `p_unit_cost` должен быть больше нуля;
- при нарушении правила функция завершает запрос ошибкой с понятным текстом;
- благодаря `STRICT` при любом аргументе `NULL` функция возвращает `NULL` без
  запуска Python-кода.

Пример использования:

```sql
SELECT lr4.delivery_total(12, 125.50);
-- 1506.00
```

### 4.2. Агрегат `lr4.weighted_avg_unit_cost`

Агрегат вычисляет средневзвешенную закупочную стоимость товара:

```text
sum(unit_cost * quantity) / sum(quantity)
```

Публичная сигнатура:

```sql
lr4.weighted_avg_unit_cost(unit_cost numeric, quantity integer) -> numeric
```

Для агрегата создаются две служебные функции на PL/Python:

```sql
lr4.weighted_avg_unit_cost_sfunc(
    state numeric[],
    unit_cost numeric,
    quantity integer
) RETURNS numeric[]

lr4.weighted_avg_unit_cost_final(
    state numeric[]
) RETURNS numeric
```

Состояние `numeric[]` содержит два элемента:

1. накопленную стоимость `sum(unit_cost * quantity)`;
2. накопленное количество `sum(quantity)`.

Определение агрегата:

```sql
CREATE AGGREGATE lr4.weighted_avg_unit_cost(numeric, integer) (
    SFUNC = lr4.weighted_avg_unit_cost_sfunc,
    STYPE = numeric[],
    FINALFUNC = lr4.weighted_avg_unit_cost_final,
    INITCOND = '{0,0}'
);
```

Строки с `NULL` в стоимости или количестве не участвуют в расчёте. Нулевое или
отрицательное количество считается ошибкой данных. Для пустой группы финальная
функция возвращает `NULL`.

Пример использования:

```sql
SELECT
    product_id,
    lr4.weighted_avg_unit_cost(unit_cost, quantity) AS weighted_cost
FROM public.deliveries
GROUP BY product_id;
```

### 4.3. Табличная функция `lr4.supplier_delivery_summary`

Сигнатура:

```sql
CREATE OR REPLACE FUNCTION lr4.supplier_delivery_summary(
    p_from timestamp without time zone,
    p_to timestamp without time zone
)
RETURNS TABLE (
    supplier_id bigint,
    supplier_name varchar,
    deliveries_count bigint,
    total_quantity bigint,
    total_cost numeric
)
LANGUAGE plpython3u
STABLE;
```

Функция возвращает статистику поставщиков за полуоткрытый интервал
`[p_from, p_to)`. Полуоткрытый интервал исключает двойной учёт поставки на
границе соседних периодов.

Python-тело выполняет один подготовленный запрос через SPI:

```sql
SELECT
    s.supplier_id,
    s.name AS supplier_name,
    count(d.delivery_id) AS deliveries_count,
    coalesce(sum(d.quantity), 0)::bigint AS total_quantity,
    coalesce(sum(d.quantity * d.unit_cost), 0) AS total_cost
FROM public.suppliers AS s
JOIN public.deliveries AS d ON d.supplier_id = s.supplier_id
WHERE d.delivered_at >= $1 AND d.delivered_at < $2
GROUP BY s.supplier_id, s.name
ORDER BY total_cost DESC, s.supplier_id;
```

План создаётся через `plpy.prepare` с типами параметров `timestamp` и хранится
в словаре `SD`, чтобы повторные вызовы в одном сеансе не готовили его заново.
Функция проверяет, что оба аргумента заданы и `p_from < p_to`, после чего
возвращает список словарей, соответствующих колонкам `RETURNS TABLE`.

Пример использования:

```sql
SELECT *
FROM lr4.supplier_delivery_summary(
    timestamp '2026-01-01 00:00:00',
    timestamp '2026-02-01 00:00:00'
);
```

### 4.4. Пользовательский тип `lr4.positive_quantity`

В PostgreSQL полноценный базовый тип требует функций ввода и вывода, обычно
написанных на C или другом низкоуровневом языке. Это противоречит ограничению
«только `psql` и PL/Python». Поэтому эквивалентом пользовательского типа в
данной работе будет домен PostgreSQL над `integer`.

Сначала создаётся неизменяемая функция проверки:

```sql
CREATE OR REPLACE FUNCTION lr4.is_positive_quantity(p_value integer)
RETURNS boolean
LANGUAGE plpython3u
IMMUTABLE;
```

Она возвращает `TRUE` для `NULL` или целого числа больше нуля. Разрешение
`NULL` соответствует рекомендации PostgreSQL для доменов; обязательность
значения задаётся в процедуре или ограничении конкретной колонки.

Затем создаётся пользовательский тип:

```sql
CREATE DOMAIN lr4.positive_quantity AS integer
CONSTRAINT positive_quantity_check
CHECK (lr4.is_positive_quantity(VALUE));
```

Домен используется в сигнатуре процедуры `lr4.register_delivery`, поэтому он
участвует в рабочем сценарии, а не существует только как демонстрационный
объект.

Примеры:

```sql
SELECT 5::lr4.positive_quantity;
-- 5

SELECT 0::lr4.positive_quantity;
-- ERROR: value for domain lr4.positive_quantity violates check constraint
```

### 4.5. Процедура `lr4.register_delivery`

Сигнатура:

```sql
CREATE OR REPLACE PROCEDURE lr4.register_delivery(
    p_supplier_id bigint,
    p_product_id bigint,
    p_warehouse_id bigint,
    p_delivered_at timestamp without time zone,
    p_quantity lr4.positive_quantity,
    p_unit_cost numeric,
    p_batch_number varchar,
    p_quality_status varchar,
    p_expires_on date DEFAULT NULL
)
LANGUAGE plpython3u
SECURITY INVOKER;
```

Процедура регистрирует одну строку в `public.deliveries`.

Алгоритм:

1. Отклонить `NULL` в `p_quantity` и значения `p_unit_cost <= 0`.
2. Проверить, что `p_quality_status` входит в `accepted`, `inspection`,
   `rejected`.
3. Подготовить параметризованный `INSERT` через `plpy.prepare` и сохранить план
   в `SD`.
4. Выполнить `INSERT ... RETURNING delivery_id`.
5. Вывести созданный `delivery_id` через `plpy.notice`.
6. Преобразовать `ForeignKeyViolation`, `UniqueViolation` и
   `CheckViolation` в сообщения, указывающие нарушенное бизнес-правило.

Проверка наличия поставщика, товара и склада отдельными `SELECT` не выполняется:
она создала бы окно гонки. Целостность гарантируют существующие внешние ключи, а
процедура обрабатывает полученную от PostgreSQL ошибку.

Пример вызова:

```sql
CALL lr4.register_delivery(
    1,
    1,
    1,
    timestamp '2026-01-10 12:00:00',
    25::lr4.positive_quantity,
    110.50,
    'LR4-BATCH-001',
    'accepted',
    NULL
);
```

### 4.6. Триггер аудита поставок

Для хранения аудита создаётся таблица:

```sql
CREATE TABLE IF NOT EXISTS lr4.delivery_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation varchar(6) NOT NULL
        CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    delivery_id bigint NOT NULL,
    changed_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    changed_by text NOT NULL DEFAULT session_user,
    old_row jsonb,
    new_row jsonb
);
```

Триггерная функция:

```sql
CREATE OR REPLACE FUNCTION lr4.audit_delivery()
RETURNS trigger
LANGUAGE plpython3u;
```

Функция читает `TD['event']`, `TD['old']` и `TD['new']`. Снимки строк
сериализуются стандартным модулем Python `json`; даты, время и `Decimal`
преобразуются в строки через `default=str`. Вставка в журнал выполняется
подготовленным планом, а текст JSON приводится к `jsonb` внутри SQL.

На таблицу поставок устанавливается один построчный триггер:

```sql
CREATE TRIGGER deliveries_audit_trg
AFTER INSERT OR UPDATE OR DELETE ON public.deliveries
FOR EACH ROW
EXECUTE FUNCTION lr4.audit_delivery();
```

Для `INSERT` заполняется только `new_row`, для `DELETE` - только `old_row`, для
`UPDATE` - обе колонки. Триггер не изменяет исходную строку. Запись аудита
входит в ту же транзакцию, что и изменение поставки, поэтому при откате
исходной операции аудит также откатывается.

## 5. Структура файлов реализации

```text
lr4/
├── docs/
│   ├── RFC.md
│   └── task.pdf
├── sql/
│   ├── install.sql
│   ├── 00_preflight.sql
│   ├── 01_schema_and_type.sql
│   ├── 02_scalar_function.sql
│   ├── 03_aggregate.sql
│   ├── 04_table_function.sql
│   ├── 05_procedure.sql
│   ├── 06_trigger.sql
│   └── uninstall.sql
└── tests/
    └── test_lr4.sql
```

`install.sql` содержит только метакоманды `\ir` в указанном порядке. Каждый
SQL-файл начинается с `\set ON_ERROR_STOP on`. Скрипт `uninstall.sql` удаляет
только объекты схемы `lr4` и триггер `public.deliveries_audit_trg`; таблицы из
предыдущих лабораторных работ не изменяются и не удаляются.

## 6. Порядок развертывания

Развертывание выполняется из корня проекта:

```bash
psql -X \
  -v ON_ERROR_STOP=1 \
  -d supply_lab \
  -f lr4/sql/install.sql
```

Последовательность внутри `install.sql`:

1. Убедиться, что `server_version_num` находится в диапазоне PostgreSQL 17.
2. Проверить доступность и создать `plpython3u`.
3. Создать схему `lr4`.
4. Создать функцию проверки и домен `lr4.positive_quantity`.
5. Создать скалярную функцию.
6. Создать переходную и финальную функции, затем агрегат.
7. Создать табличную функцию.
8. Создать процедуру.
9. Создать таблицу аудита, триггерную функцию и триггер.
10. Выполнить проверки наличия объектов по системным каталогам.

Установка считается успешной только при коде возврата `psql`, равном нулю.

## 7. Тестирование

### 7.1. Принцип

Автоматический тест находится в `lr4/tests/test_lr4.sql` и запускается только
через `psql`. Тест начинается с `BEGIN`, создаёт собственные строки с префиксом
`LR4-TEST`, проверяет все шесть объектов и завершается `ROLLBACK`. После
успешного или неуспешного теста рабочие данные не должны измениться.

Для проверок используются анонимные блоки:

```sql
DO LANGUAGE plpython3u $$
result = plpy.execute("SELECT ...")[0]
if result["actual"] != result["expected"]:
    plpy.error("описание нарушенного ожидания")
$$;
```

Ожидаемые ошибки также перехватываются в `DO LANGUAGE plpython3u` через
`plpy.SPIError`. Если ошибочный вызов неожиданно завершается успешно, тестовый
блок вызывает `plpy.error`.

Запуск:

```bash
psql -X \
  -v ON_ERROR_STOP=1 \
  -d supply_lab \
  -f lr4/tests/test_lr4.sql
```

### 7.2. Подготовка фикстур

Внутри тестовой транзакции создаются:

- поставщик с уникальными `tax_id` и `email`;
- товар с уникальным `sku`;
- склад с уникальным `code`;
- две поставки одного товара от одного поставщика на один склад с разными
  номерами партии.

Идентификаторы сохраняются средствами `psql`:

```sql
INSERT INTO public.suppliers (...)
VALUES (...)
RETURNING supplier_id AS test_supplier_id \gset
```

Аналогично сохраняются `test_product_id` и `test_warehouse_id`.

### 7.3. Матрица проверок

| Объект | Позитивная проверка | Негативная или граничная проверка |
| --- | --- | --- |
| `lr4.delivery_total` | `delivery_total(12, 125.50) = 1506.00` | нулевое количество вызывает ошибку; `NULL` возвращает `NULL` |
| `lr4.weighted_avg_unit_cost` | для `(10, 2)` и `(20, 3)` результат равен `16.00` | пустой набор возвращает `NULL`; отрицательный вес вызывает ошибку |
| `lr4.supplier_delivery_summary` | возвращает одну строку с ожидаемыми количеством и суммой | поставка на правой границе `p_to` не учитывается; `p_from >= p_to` вызывает ошибку |
| `lr4.positive_quantity` | приведение `5::lr4.positive_quantity` успешно | приведение `0` и `-1` вызывает нарушение ограничения домена |
| `lr4.register_delivery` | после `CALL` появляется ровно одна поставка с заданным `batch_number` | неизвестный внешний ключ, повторный бизнес-ключ и недопустимый статус вызывают ошибку |
| `deliveries_audit_trg` | `INSERT`, `UPDATE`, `DELETE` создают три записи аудита с корректными снимками | после отката отдельной точки сохранения изменение и его аудит отсутствуют |

### 7.4. Проверка состава объектов

В конце теста до `ROLLBACK` проверяются системные каталоги:

```sql
SELECT p.proname, p.prokind, l.lanname
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
JOIN pg_language AS l ON l.oid = p.prolang
WHERE n.nspname = 'lr4'
ORDER BY p.proname;

SELECT typname, typtype
FROM pg_type AS t
JOIN pg_namespace AS n ON n.oid = t.typnamespace
WHERE n.nspname = 'lr4'
  AND typname = 'positive_quantity';

SELECT tgname, tgenabled
FROM pg_trigger
WHERE tgrelid = 'public.deliveries'::regclass
  AND tgname = 'deliveries_audit_trg'
  AND NOT tgisinternal;
```

Ожидания:

- прикладные функции и процедура используют язык `plpython3u`;
- `positive_quantity` имеет `typtype = 'd'`, то есть является доменом;
- триггер существует и включён;
- агрегат `lr4.weighted_avg_unit_cost(numeric, integer)` разрешается через
  `to_regprocedure`.

### 7.5. Ручная демонстрация

Для защиты лабораторной работы рекомендуется выполнить в интерактивном
`psql`:

```sql
\x on

SELECT lr4.delivery_total(quantity, unit_cost) AS delivery_total
FROM public.deliveries
ORDER BY delivery_id
LIMIT 5;

SELECT product_id,
       lr4.weighted_avg_unit_cost(unit_cost, quantity) AS weighted_cost
FROM public.deliveries
GROUP BY product_id
ORDER BY product_id
LIMIT 5;

SELECT *
FROM lr4.supplier_delivery_summary(
    timestamp '2020-01-01 00:00:00',
    timestamp '2030-01-01 00:00:00'
)
LIMIT 5;

SELECT audit_id, operation, delivery_id, changed_at, old_row, new_row
FROM lr4.delivery_audit
ORDER BY audit_id DESC
LIMIT 5;
```

## 8. Обработка ошибок и безопасность

- Функции получают параметры как значения, а не как фрагменты SQL.
- Подготовленные планы сохраняются в `SD` отдельно для каждого объекта.
- Ошибки SPI перехватываются только там, где добавляется предметный контекст;
  неизвестные ошибки не маскируются.
- Процедура работает с `SECURITY INVOKER` и не повышает привилегии вызывающего.
- На схему `lr4` не выдаётся `CREATE` роли приложения.
- Функция доменного ограничения остаётся `IMMUTABLE`. При изменении её логики
  ограничение домена необходимо удалить и создать повторно, чтобы PostgreSQL
  перепроверил существующие значения.
- Табличная функция ограничена заданным временным интервалом. Если объём
  результата станет большим, реализацию следует перевести с `plpy.execute` на
  `plpy.cursor`.

## 9. Критерии готовности

Реализация завершена, когда выполняются все условия:

1. `install.sql` с чистого состояния завершается с кодом ноль.
2. В схеме `lr4` существуют все шесть требуемых публичных объектов.
3. Все процедурные функции, процедура и триггерная функция используют только
   `plpython3u`.
4. Домен `lr4.positive_quantity` отклоняет ноль и отрицательные значения.
5. Процедура создаёт поставку и сохраняет ограничения исходной модели данных.
6. Триггер фиксирует `INSERT`, `UPDATE` и `DELETE` в одной транзакции с
   изменением поставки.
7. `test_lr4.sql` завершается с кодом ноль и не оставляет тестовых данных.
8. Повторный запуск `install.sql` не создаёт дубликаты триггеров и не изменяет
   таблицы предыдущих лабораторных работ.

## 10. Документация PostgreSQL

- [PL/Python functions](https://www.postgresql.org/docs/17/plpython-funcs.html)
- [PL/Python database access](https://www.postgresql.org/docs/17/plpython-database.html)
- [PL/Python trigger functions](https://www.postgresql.org/docs/17/plpython-trigger.html)
- [User-defined aggregates](https://www.postgresql.org/docs/17/xaggr.html)
- [CREATE DOMAIN](https://www.postgresql.org/docs/17/sql-createdomain.html)
- [CREATE TYPE](https://www.postgresql.org/docs/17/sql-createtype.html)
