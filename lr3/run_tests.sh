#!/usr/bin/env bash

set -Eeuo pipefail

lr3_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lr3_container_name="${LR3_PG_CONTAINER:-lr1-postgres}"
lr3_database_user="${LR3_PGUSER:-postgres}"

run_sql_file() {
    local sql_file="$1"

    echo "==> Выполняется ${sql_file#"${lr3_script_dir}/"}"
    podman exec -i "${lr3_container_name}" \
        psql -X -v ON_ERROR_STOP=1 -U "${lr3_database_user}" -d postgres \
        < "${sql_file}"
}

if ! command -v podman >/dev/null 2>&1; then
    echo "Ошибка: команда podman не найдена" >&2
    exit 1
fi

if ! podman exec "${lr3_container_name}" true >/dev/null 2>&1; then
    echo "Ошибка: контейнер ${lr3_container_name} не найден или не запущен" >&2
    echo "Запустите его командой: podman start ${lr3_container_name}" >&2
    exit 1
fi

run_sql_file "${lr3_script_dir}/queries/00_demo_data.sql"
run_sql_file "${lr3_script_dir}/queries/01_functions.sql"
run_sql_file "${lr3_script_dir}/queries/02_procedures.sql"
run_sql_file "${lr3_script_dir}/queries/03_triggers.sql"
run_sql_file "${lr3_script_dir}/queries/04_tests.sql"

echo "==> Все модули установлены, тесты успешно пройдены"
