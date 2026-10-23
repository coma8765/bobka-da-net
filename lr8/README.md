# ЛР8: загрузка событий поставок через Apache NiFi

Генератор раз в 5 минут создаёт JSON с 1–20 новыми событиями приёмки поставок.
NiFi проверяет файл целиком, преобразует и разделяет JSON, собирает записи
обратно и выполняет один транзакционный INSERT в PostgreSQL 17 `supply_lab`.
Успешные файлы сохраняются в архиве, ошибочные — в `rejected`; результат
обработки записывается в JSON-квитанцию и журнал NiFi.

Используется предметная область и форматы естественных ключей из [ЛР1](../lr1/README.md).
По RFC данные поступают в отдельную таблицу `lr8.delivery_events`:
`public.deliveries` и справочники ЛР1 не изменяются. Перенос в основную модель
не входит в работу. Генератор не подключается к PostgreSQL.

## Требования

- Python 3.9+; прикладной код и тесты используют только стандартную библиотеку.
- Podman с запущенной VM, контейнер `lr1-postgres` с базой `supply_lab` из ЛР1.
- Apache NiFi **2.6.0**, PostgreSQL JDBC **42.7.7**.
- Свободный порт `127.0.0.1:8443`; PostgreSQL ЛР1 опубликован на `55432`.

Все команды ниже выполняются из каталога `lr8`. Версия NiFi 2.6.0 проверена
на настоящем сервере; [результаты проверки](docs/verification.md).

Если в этой рабочей копии уже есть `runtime/local/credentials.env`, это
локальные учётные данные созданного проверочного стенда (файл не включается
в репозиторий). Их можно загрузить командой
`source runtime/local/credentials.env`. Контейнер `lr8-nifi` и поток уже созданы:
для повторного запуска достаточно `podman start lr1-postgres lr8-nifi`,
повторный импорт не нужен.

## Запуск

```bash
podman machine start
podman start lr1-postgres
podman exec lr1-postgres pg_isready -U postgres -d supply_lab
podman exec -i lr1-postgres psql -X -U postgres -d supply_lab < sql/install.sql
```

Дождитесь `accepting connections` перед установкой таблицы. Установка повторяема,
но не мигрирует несовместимую таблицу, если та уже создана вручную.
Для локального PostgreSQL вместо `podman exec` можно использовать `psql`.

Задайте пароль NiFi (не короче 12 символов), затем запустите контейнер:

```bash
export NIFI_USERNAME=student
read -s 'NIFI_PASSWORD?Пароль NiFi: '
export NIFI_PASSWORD
sh scripts/start_nifi.sh
podman logs -f lr8-nifi
```

`read` выше использует синтаксис zsh (macOS). В bash: `read -s -p 'Пароль NiFi: ' NIFI_PASSWORD`.
Скрипт скачивает JDBC-драйвер с Maven Central. При повторном запуске существующего
контейнера используйте `podman start lr8-nifi`. UI: <https://localhost:8443/nifi/>.
Сертификат локального контейнера самоподписанный; первый запуск может занять несколько минут.

Импортировать и запустить поток можно через API:

```bash
export NIFI_INSECURE=1
read -s 'PGPASSWORD?Пароль PostgreSQL из ЛР1: '
export PGPASSWORD
python3 scripts/import_flow.py
```

В ЛР1 стандартный пароль PostgreSQL — `postgres`. API-скрипт передаёт его в
sensitive parameter, проверяет JDBC-соединение, валидность всех процессоров и запускает поток.
Повторный импорт одноимённой группы запрещён, чтобы не создать второй обработчик.
`NIFI_INSECURE=1` отключает проверку сертификата только у данного локального клиента.
Для собственного сертификата не задавайте эту переменную.

Можно импортировать `nifi/lr8-delivery-import.json` через интерфейс, заполнить
параметры и запустить группу вручную — подробности в [описании потока](docs/nifi-flow.md).
По умолчанию JDBC подключается через `host.containers.internal:55432`.
Для другой БД задайте `JDBC_URL` и `PGUSER` до запуска API-скрипта.

```bash
python3 src/generator.py --once
python3 src/generator.py --watch
```

Без аргументов генератор также работает непрерывно. `--interval 300` — значение
по умолчанию; `--interval 10` удобно для короткой демонстрации. `Ctrl+C` завершает
процесс. `--count 20` задаёт размер файла, `--runtime PATH` — каталог обмена.
`inbox` и `outbox` должны находиться на одной файловой системе для атомарного rename.

## Результаты

- `runtime/archive/YYYY-MM-DD/<source-name>` — исходный JSON после фиксации БД.
- `runtime/receipts/<source-name>.loaded.json` — квитанция успешной обработки.
- `runtime/rejected/<source-name>.<source-uuid>.rejected.json` — ошибочный файл.
- Рядом с ошибочным файлом — `<имя>.error.json` с этапом, причиной и UUID.
- NiFi Data Provenance и `LogAttribute` — история движения и итоговый статус.

`loaded` журналируется только после сохранения архива и квитанции. При отказе
диска поток повторяет запись файлов, не обращаясь к INSERT повторно. При
перезапуске между COMMIT БД и фиксацией NiFi-сессии возможна повторная доставка:
уникальные ключи исключают дубли, но файл попадёт в ошибки. Такой случай нужно
сверить с БД по `file_id`; распределённой транзакции между БД и NiFi здесь нет.

## Проверки

```bash
python3 -m unittest discover -s tests -v
podman exec -i lr1-postgres psql -X -U postgres -d supply_lab < tests/test_database.sql
```

SQL-тест выполняется в транзакции с `ROLLBACK`. Сверка конкретного загруженного файла:

```bash
podman exec -i lr1-postgres psql -X -U postgres -d supply_lab \
  -v file_id=UUID_ИЗ_ИМЕНИ -v expected_count=ЧИСЛО_ЗАПИСЕЙ < tests/verify_database.sql
```

Полный сценарий проверки NiFi описан в [docs/nifi-flow.md](docs/nifi-flow.md).
Фикстуры используют имя
`550e8400-e29b-41d4-a716-446655440000__delivery_events__20260912T120000Z.json`;
не копируйте `valid.json` напрямую без переименования.

## Хранение и остановка

Скрипт запуска монтирует `runtime` для обмена, `src` и JDBC только для чтения.
Конфигурация, content/FlowFile/provenance/database repositories, state и логи
находятся в отдельных именованных томах `lr8-nifi-*`. Обычный перезапуск сохраняет
очереди и конфигурацию. Секреты остаются в локальном защищённом хранилище NiFi;
экспорт потока их не содержит.

```bash
podman stop lr8-nifi
```

Генератор останавливается отдельно через `Ctrl+C`. `sql/uninstall.sql` удаляет
только таблицу ЛР8 и её схему вместе с данными; запускать его следует лишь при
намеренном удалении результатов работы.
