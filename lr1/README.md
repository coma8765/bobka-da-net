# Лабораторная работа № 1

Предметная область — поставки товаров. Таблица `deliveries` реализует тернарное
отношение многие-ко-многим между поставщиками, товарами и складами и содержит
собственные атрибуты поставки.

## Генерация данных

```bash
python3 generator/generate_data.py
```

Команда детерминированно создаёт по 1000 строк для каждой родительской таблицы,
3000 складских секций с рекурсивной иерархией и 5000 поставок в каталоге
`data`.

CSV-файлы не содержат суррогатные идентификаторы. При массовой загрузке поля
`IDENTITY` заполняются PostgreSQL автоматически, поэтому дополнительная
синхронизация sequences через `setval` не требуется.

## Запуск PostgreSQL в Podman

Из корня проекта:

```bash
podman machine start
podman run --name lr1-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 55432:5432 \
  -v "$PWD:/workspace:Z" \
  -w /workspace \
  -d docker.io/library/postgres:17-alpine
```

Если контейнер уже создан, достаточно запустить его командой
`podman start lr1-postgres`.

Последовательный запуск сценариев из командной строки:

```bash
podman exec lr1-postgres psql -U postgres -d postgres -f queries/01_create_database_and_tables.sql
podman exec lr1-postgres psql -U postgres -d postgres -f queries/02_add_constraints.sql
podman exec lr1-postgres psql -U postgres -d postgres -f queries/03_bulk_load.sql
```

Запуск всех сценариев через Python и Psycopg:

```bash
python3 -m pip install -r requirements.txt
python3 src/__main__.py
```

По умолчанию используются `127.0.0.1:55432`, пользователь `postgres` и пароль
`postgres`. Параметры можно переопределить переменными `PGHOST`, `PGPORT`,
`PGUSER` и `PGPASSWORD`.

Подключение из графического клиента: сервер `localhost`, порт `55432`, база
`supply_lab`, пользователь `postgres`, пароль `postgres`. В клиенте сценарии
следует выполнить в том же порядке.

## ER-диаграмма

Диаграмма выполнена в нотации Чена. Исходник находится в
`docs/er-diagram.dot`. Его можно открыть и редактировать в любом
Graphviz-совместимом редакторе. Готовое изображение — `docs/er-diagram.svg`.
