# Лабораторная работа № 5

Работа выполнена для PostgreSQL 17 и базы `supply_lab` из ЛР 1. Формат обмена:
UTF-8 JSON Lines; формат документов в базе - `jsonb`.

Краткое описание использованных SQL- и Psycopg-конструкций приведено в
[`docs/REFERENCE.md`](docs/REFERENCE.md).

## Состав работы

- `sql/00_schema.sql` создаёт схему `lr5`, реляционную таблицу для обратной
  загрузки и таблицу JSONB-документов.
- `sql/01_build_documents.sql` формирует вложенные документы поставок.
- `sql/02_json_operations.sql` демонстрирует извлечение фрагмента и значения,
  проверку существования, изменение документа и разворачивание массива.
- `src/export_deliveries.py` потоково экспортирует `public.deliveries` в
  `data/deliveries.jsonl` с атомарной заменой файла.
- `src/import_deliveries.py` атомарно загружает JSONL и проверяет полное
  совпадение с исходной таблицей.

Параметры подключения читаются из `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`
и `PGPASSWORD`. Значения по умолчанию соответствуют окружению ЛР 1:
`127.0.0.1:55432`, база `supply_lab`, пользователь и пароль `postgres`.

## Запуск

Из корня репозитория:

```bash
python3 -m pip install -r lr5/requirements.txt
psql -X -v ON_ERROR_STOP=1 -d supply_lab -f lr5/sql/install.sql
python3 lr5/src/export_deliveries.py
python3 lr5/src/import_deliveries.py
psql -X -v ON_ERROR_STOP=1 -d supply_lab \
  -f lr5/sql/02_json_operations.sql
```

## Проверка

```bash
psql -X -v ON_ERROR_STOP=1 -d supply_lab \
  -f lr5/tests/test_json_operations.sql
python3 -m unittest lr5/tests/test_roundtrip.py
```

Удаление объектов ЛР 5:

```bash
psql -X -v ON_ERROR_STOP=1 -d supply_lab -f lr5/sql/uninstall.sql
```
