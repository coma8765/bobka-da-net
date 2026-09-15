#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
container_name="${PG_CONTAINER:-lr1-postgres}"
database_name="${PGDATABASE:-supply_lab}"
database_user="${PGUSER:-postgres}"

if ! command -v podman >/dev/null 2>&1; then
    printf 'Ошибка: команда podman не найдена.\n' >&2
    exit 1
fi

if ! podman info >/dev/null 2>&1; then
    printf 'Запуск Podman VM...\n'
    podman machine start
fi

if ! podman container exists "$container_name"; then
    printf 'Ошибка: контейнер %s не найден.\n' "$container_name" >&2
    exit 1
fi

if [ "$(podman inspect --format '{{.State.Running}}' "$container_name")" != 'true' ]; then
    printf 'Запуск контейнера %s...\n' "$container_name"
    podman start "$container_name" >/dev/null
fi

printf 'Ожидание готовности PostgreSQL...\n'
postgres_ready=false
for _ in {1..30}; do
    if podman exec "$container_name" pg_isready -U "$database_user" >/dev/null 2>&1; then
        postgres_ready=true
        break
    fi
    sleep 1
done

if [ "$postgres_ready" != 'true' ]; then
    printf 'Ошибка: PostgreSQL не запустился за 30 секунд.\n' >&2
    exit 1
fi

for query_file in "$script_dir"/queries/query_*.sql; do
    query_name="$(basename -- "$query_file")"
    printf '\n========== %s ==========\n\n' "$query_name"
    podman exec -i "$container_name" \
        psql \
        -X \
        -v ON_ERROR_STOP=1 \
        -P pager=off \
        -U "$database_user" \
        -d "$database_name" \
        < "$query_file"
done

printf '\nВсе запросы выполнены успешно.\n'
