# Поток lr8-delivery-import

Экспорт: `nifi/lr8-delivery-import.json`. Воспроизводимая сборка экспорта:
`python3 scripts/build_flow.py`. Версия компонентов закреплена на NiFi 2.6.0.
Схема записи: `nifi/delivery-event.avsc`; полный контракт: `src/validation.py`.

## Импорт через UI

1. Запустите контейнер командой из README и войдите в <https://localhost:8443/nifi/>.
2. Создайте Process Group, выбрав загрузку flow definition из JSON-файла
   `nifi/lr8-delivery-import.json` (Upload Flow Definition).
3. В Parameter Context `lr8` задайте `jdbc.url`, `jdbc.user` и sensitive-параметр
   `jdbc.password`. Стандартный URL:
   `jdbc:postgresql://host.containers.internal:55432/supply_lab?stringtype=unspecified&logServerErrorDetail=false`.
4. В настройках группы откройте Controller Services. Включите `JSON reader`,
   `JSON writer`, `PostgreSQL supply_lab`. `Validation-query=SELECT 1` проверяет
   соединение при выдаче JDBC connection. До запуска группы выполните Verify
   в настройках DBCP и проверьте успешный результат подключения. API-скрипт
   выполняет эту проверку автоматически.
5. Убедитесь, что все процессоры валидны. Запустите группу.
6. Выполните `python3 src/generator.py --once` и дождитесь квитанции в `receipts`.

Для `ExecuteStreamCommand` нужен доступ к restricted components / execute code;
локальный single-user администратор имеет этот доступ. Команда запускается прямо
как `/usr/bin/python3`, без shell. Аргумент имени файла передаётся только после
проверки маски. Код не имеет сетевого доступа к БД и не выполняет INSERT.

## Controller Services

| Имя | Тип | Ключевые свойства |
| --- | --- | --- |
| JSON reader | JsonTreeReader | schema-text-property, встроенный delivery-event.avsc, Date Format `yyyy-MM-dd`, Timestamp Format `yyyy-MM-dd'T'HH:mm:ss'Z'` |
| JSON writer | JsonRecordSetWriter | inherit-record-schema, no-schema, output-array, те же форматы дат |
| PostgreSQL supply_lab | DBCPConnectionPool | org.postgresql.Driver, `/opt/nifi/jdbc/postgresql.jar`, URL/user/password из Parameter Context |

Контейнер работает в UTC. Для UUID JDBC URL содержит `stringtype=unspecified&logServerErrorDetail=false`:
PostgreSQL определяет тип строкового параметра из типа целевой колонки.
`logServerErrorDetail=false` исключает значения параметров из JDBC-ошибок;
в квитанции БД сохраняется причина без текста INSERT.
Avro `timestamp-millis` и `date` обеспечивают типизированные даты в JDBC.

## Процессоры и маршруты

Точные API-имена и значения всех свойств сохранены в JSON и `build_flow.py`.
Ниже приведены назначения, основные настройки и обработка ошибок.

| Процессор | Свойства и маршрут |
| --- | --- |
| Read inbox / GetFile | Input Directory `/opt/nifi/lr8/runtime/inbox`, File Filter `.*\.json`, Keep Source File=false, период 10 sec, Batch Size=20 |
| Remember source / UpdateAttribute | Сохраняет source.filename, source.uuid, file_id, table_name, formed_at; исходный статус processing |
| Check filename and size / RouteOnAttribute | UUID4 + delivery_events + UTC-время; не более 1 MiB; unmatched → Mark rejected |
| Remember original bytes / ExtractText | Сохраняет полный исходный UTF-8 JSON в original.content, лимит 1 MiB; unmatched → Mark rejected |
| Validate complete file / ExecuteStreamCommand | `/usr/bin/python3 /opt/nifi/lr8/src/validate_file.py <имя>`; stdin = исходный файл; original → Check validation result |
| Check validation result / RouteOnAttribute | execution.status=0 → Validate record schema; unmatched → Validation error → Mark rejected |
| Validate record schema / ValidateRecord | Reader + Writer, явная Avro-схема, Strict Type Checking=true, Allow Extra Fields=false, Force Types From Reader Schema=true |
| Convert to JSON / ConvertRecord | Reader + Writer, record.count сохраняется в record_count |
| Split array / SplitJson | JsonPath Expression `$[*]`, split → Reassemble file |
| Reassemble file / MergeContent | Defragment, Binary Concatenation, Text, Header `[`, Footer `]`, Demarcator `,`, Max Bin Age=1 min |
| Restore filename / UpdateAttribute | Возвращает source.filename после split/merge |
| Insert whole file / PutDatabaseRecord | PostgreSQL, INSERT, schema lr8, table delivery_events, AutoCommit=false, неизвестные поля запрещены; retry → Retry database, failure → Classify database failure |
| Classify database failure / RouteOnAttribute | Известные нарушения ограничений → Database error; ошибки соединения и остальные ошибки → Retry database |
| Retry database / RetryFlowFile | Penalize Retries=true, penalty 30 sec; после 10 попыток счётчик сбрасывается, файл остаётся в цикле ожидания |
| Mark committed / UpdateAttribute | Фиксирует committed_at, archive.date и статус committed |
| Restore archived original / ReplaceText | Always Replace / Entire text: возвращает original.content |
| Archive source / PutFile | archive/${archive.date}, Conflict Resolution Strategy=replace; success → Loaded receipt name |
| Loaded receipt / AttributesToJSON | Формирует JSON из белого списка атрибутов |
| Save loaded receipt / PutFile | receipts/<source.filename>.loaded.json; success → Log loaded |
| Log loaded / LogAttribute | INFO, только служебные атрибуты, Log Payload=false |
| Transformation error / UpdateAttribute | failure/invalid преобразований → Restore rejected original → Mark rejected |
| Mark rejected / UpdateAttribute | Статус rejected, время и уникальное имя с source.uuid |
| Save rejected / PutFile | Сохраняет исходный файл; success → Rejected receipt name → Rejected receipt |
| Save rejected receipt / PutFile | Сохраняет JSON с причиной и стадией рядом с файлом; success → Log rejected |
| Log rejected / LogAttribute | WARN, только служебные атрибуты, Log Payload=false |

Все `PutFile.failure` и `AttributesToJSON.failure` повторяют тот же шаг. `ReplaceText.failure` повторяет
восстановление. После COMMIT ни один путь не возвращается к INSERT.
Ошибки выполнения самой команды (например, отсутствует Python) приводят к
bulletin/yield процессора; исходный FlowFile остаётся в очереди.

Явно auto-terminate только:

- `SplitJson.original`: исходник уже сохранён в атрибуте и в provenance.
- `MergeContent.original`: фрагменты заменены одним полным FlowFile.
- `ExecuteStreamCommand.output stream/nonzero status`: stdout является копией,
  решение принимается по `execution.status` исходного FlowFile.
- `Log loaded.success` и `Log rejected.success`: конечные узлы после устойчивой записи.

Очереди: back pressure 100 объектов / 16 MB, expiration 0 sec. Поскольку
original.content сохраняется в атрибутах и переносится во фрагменты, лабораторный
контракт ограничен 20 записями и 1 MiB. Это поток для малых учебных файлов.

## Проверка целого файла

Одного ValidateRecord недостаточно: он выдаёт корректные и ошибочные записи
по разным relationships и не выдаёт результат для пустого набора. Поэтому до
него выполняется `validate_file.py`, отклоняющий весь вход при любой ошибке:

- корень не массив, пустой массив или более 20 записей;
- повреждённый JSON, не UTF-8, повторные ключи объекта, NaN/Infinity;
- отсутствующие/лишние поля, неверные JSON-типы (включая boolean вместо числа);
- недопустимые UUID, несовпадение source_file_id с именем;
- повтор event_id или batch_number внутри файла;
- пустые/длинные естественные ключи, нулевые/отрицательные числа;
- переполнение PostgreSQL integer/numeric(12,2), лишняя точность цены;
- неизвестный статус, невозможная календарная дата, неверный UTC timestamp.

Проверка бизнес-правил выполняется этим же шагом вместо QueryRecord, чтобы
не порождать независимые ветви корректных/ошибочных записей. ValidateRecord
дополнительно проверяет типизированную Avro-схему. SplitJson + MergeContent
сохраняют требуемую в задании демонстрацию разделения при атомарном INSERT.

## Журнал и восстановление

Квитанция содержит source.uuid, source.filename, file_id, record_count,
load.status, processed_at; для успеха также committed_at, для ошибки —
error.stage и error.reason. `AttributesToJSON` корректно экранирует кавычки
и переводы строк в ошибках. Повторные попытки rejected различаются source.uuid.

NiFi удаляет входной файл после приёма GetFile; далее исходник хранится в content
repository и атрибуте FlowFile. `Keep Source File=false` исключает бесконечное
чтение одного имени. Файловая система и сессия GetFile не образуют распределённую
транзакцию: при аварии возможна повторная доставка. При падении после PostgreSQL
COMMIT повторная вставка отвергается уникальными ключами. Сверяйте file_id с БД,
архивом и provenance, прежде чем вручную повторять ошибочный файл.

`PutFile` использует replace для идемпотентного повторения после сбоя диска:
архив уникален по имени с UUID4, rejected — по исходному NiFi UUID. При отказе
receipt очередь не очищается, и Log loaded не вызывается. DB commit к этому
моменту уже произошёл; отсутствие receipt не означает отсутствие данных в БД.

## Демонстрация и интеграционная проверка

```bash
python3 tests/integration.py
```

Нужны запущенный поток и доступный Podman. Тест создаёт новые события и
оставляет архив, квитанции и строки ЛР8 как свидетельство проверки. Он проверяет
успешную загрузку, неверное имя, повреждённый JSON, пустой массив, корень-объект,
отсутствующее поле, количество/цену/статус, несовпадение source_file_id, дубликат,
строковое количество, невозможную дату и повторную доставку. Для каждого
ошибочного файла проверяется ноль строк в БД; для успеха — число строк,
квитанция и побайтовое равенство архива оригиналу.

Проверка расписания: запустите `python3 src/generator.py --watch`, дождитесь
двух файлов (первый появляется сразу, второй через 300 секунд) и сравните UUID.
Для быстрой проверки можно использовать `--interval 10`.

Автоматическая проверка восстановления (временно останавливает БД и перезапускает
NiFi, затем запускает оба контейнера обратно):

```bash
python3 tests/recovery.py
```

Нужны переменные `NIFI_USERNAME`, `NIFI_PASSWORD`, `NIFI_INSECURE` из инструкции
импорта. Запускайте отдельно от других проверок, когда остальные лабораторные
клиенты остановлены.

Проверка простоя PostgreSQL вручную: остановите генератор и другие лабораторные клиенты,
остановите `lr1-postgres`, создайте один новый файл и наблюдайте очередь перед
PutDatabaseRecord/retry и bulletin. После `podman start lr1-postgres` файл должен
дойти до archive/receipt. Не очищайте очередь. Перезапуск `lr8-nifi` с теми же
томами должен сохранить ожидающие FlowFiles.

## Документация Apache

- [ValidateRecord: разделение valid/invalid и пустой набор](https://nifi.apache.org/components/org.apache.nifi.processors.standard.ValidateRecord/)
- [MergeContent: Defragment и fragment.count](https://nifi.apache.org/components/org.apache.nifi.processors.standard.MergeContent/)
- [PutDatabaseRecord: одна транзакция на FlowFile](https://nifi.apache.org/components/org.apache.nifi.processors.standard.PutDatabaseRecord/)
- [ExecuteStreamCommand: original и execution.status](https://nifi.apache.org/components/org.apache.nifi.processors.standard.ExecuteStreamCommand/)
