#!/usr/bin/env bash

set -Eeuo pipefail

# podman exec -u root lr1-postgres apk add --no-cache py3-numpy

lr4_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lr4_container_name="${LR4_PG_CONTAINER:-lr1-postgres}"
lr4_database_user="${LR4_PGUSER:-postgres}"
lr4_database_name="${LR4_PGDATABASE:-supply_lab}"

run_sql_file() {
    local sql_file="$1"

    echo "==> Выполняется ${sql_file#"${lr4_script_dir}/"}"
    podman exec -i "${lr4_container_name}" \
        psql -X -v ON_ERROR_STOP=1 \
        -U "${lr4_database_user}" \
        -d "${lr4_database_name}" \
        < "${sql_file}"
}

if ! command -v podman >/dev/null 2>&1; then
    echo "Ошибка: команда podman не найдена" >&2
    exit 1
fi

if ! podman exec "${lr4_container_name}" true >/dev/null 2>&1; then
    echo "Ошибка: контейнер ${lr4_container_name} не найден или не запущен" >&2
    echo "Запустите его командой: podman start ${lr4_container_name}" >&2
    exit 1
fi

run_sql_file "${lr4_script_dir}/sql/00_preflight.sql"
run_sql_file "${lr4_script_dir}/sql/01_schema_and_type.sql"
run_sql_file "${lr4_script_dir}/sql/02_scalar_function.sql"
run_sql_file "${lr4_script_dir}/sql/03_aggregate.sql"
run_sql_file "${lr4_script_dir}/sql/04_table_function.sql"
run_sql_file "${lr4_script_dir}/sql/05_procedure.sql"
run_sql_file "${lr4_script_dir}/sql/06_trigger.sql"
run_sql_file "${lr4_script_dir}/sql/07_numpy_gradient.sql"
run_sql_file "${lr4_script_dir}/tests/test_lr4.sql"

echo "==> Все объекты ЛР 4 установлены, тесты успешно пройдены"
