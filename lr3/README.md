# Лабораторная работа № 3

Работа расширяет базу PostgreSQL `supply_lab` из `lr1` десятью SQL-модулями:
четырьмя функциями, четырьмя хранимыми процедурами и двумя DML-триггерами.
Описание решения находится в `docs/RFC.md`.

Дополнительно реализована функция
`fn_refresh_yesterday_warehouse_stats(p_limit)`. Она создаёт таблицу
с датой в имени, например `warehouse_daily_stats_2026_09_10`, рассчитывает
топ складов за вчера по числу поставок и возвращает сохранённый снимок. По
умолчанию сохраняются пять складов.

Пример ручного запуска:

```sql
SELECT * FROM public.fn_refresh_yesterday_warehouse_stats(5);
```

## Состав

- `queries/01_functions.sql` — скалярная, подставляемая табличная,
  многооператорная табличная и рекурсивная функции;
- `queries/02_procedures.sql` — обычная и рекурсивная процедуры, процедура с
  курсором и процедура доступа к метаданным;
- `queries/03_triggers.sql` — представление, триггер `AFTER` и триггер
  `INSTEAD OF` с обязательными триггерными функциями;
- `queries/04_tests.sql` — автоматические проверки всех модулей.

## Подготовка базы

Сначала нужно развернуть `lr1` в порядке, указанном в `lr1/README.md`:

```bash
cd lr1
python3 src/__main__.py
cd ..
```

## Установка модулей

При установленном клиенте `psql` из корня проекта:

```bash
psql -h 127.0.0.1 -p 55432 -U postgres -d postgres -f lr3/queries/01_functions.sql
psql -h 127.0.0.1 -p 55432 -U postgres -d postgres -f lr3/queries/02_procedures.sql
psql -h 127.0.0.1 -p 55432 -U postgres -d postgres -f lr3/queries/03_triggers.sql
```

Если PostgreSQL работает в контейнере `lr1-postgres`, сценарии можно передать
через стандартный ввод:

```bash
podman exec -i lr1-postgres psql -U postgres -d postgres < lr3/queries/01_functions.sql
podman exec -i lr1-postgres psql -U postgres -d postgres < lr3/queries/02_procedures.sql
podman exec -i lr1-postgres psql -U postgres -d postgres < lr3/queries/03_triggers.sql
```

## Тестирование

Тесты выполняются в одной транзакции и завершаются `ROLLBACK`, поэтому не
изменяют данные из `lr1`:

```bash
./lr3/run_tests.sh
```

Скрипт последовательно устанавливает функции, процедуры и триггеры, после
чего запускает все проверки. По умолчанию используется контейнер
`lr1-postgres` и пользователь `postgres`. Их можно переопределить:

```bash
LR3_PG_CONTAINER=my-postgres LR3_PGUSER=my-user ./lr3/run_tests.sh
```

Ручной запуск тестового сценария через локальный `psql`:

```bash
psql -h 127.0.0.1 -p 55432 -U postgres -d postgres -f lr3/queries/04_tests.sql
```

Для контейнера:

```bash
podman exec -i lr1-postgres psql -U postgres -d postgres < lr3/queries/04_tests.sql
```

Все сценарии включают `ON_ERROR_STOP`; ненулевой код завершения означает
ошибку установки или проверки.
