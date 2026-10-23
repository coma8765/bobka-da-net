#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${NIFI_USERNAME:=student}"
: "${NIFI_PASSWORD:?Set NIFI_PASSWORD (at least 12 characters)}"
if [ "${#NIFI_PASSWORD}" -lt 12 ]; then
    echo 'NIFI_PASSWORD must have at least 12 characters' >&2
    exit 1
fi
mkdir -p runtime/inbox runtime/outbox runtime/archive runtime/rejected runtime/receipts runtime/jdbc
if [ ! -s runtime/jdbc/postgresql.jar ]; then
    curl --fail --location --output runtime/jdbc/postgresql.jar.tmp \
        https://repo.maven.apache.org/maven2/org/postgresql/postgresql/42.7.7/postgresql-42.7.7.jar
    mv runtime/jdbc/postgresql.jar.tmp runtime/jdbc/postgresql.jar
fi
# NiFi image runs as UID 1000. Podman :U would change ownership of source files.
# Only the exchange directories are made writable for this local laboratory.
chmod a+rwx runtime/inbox runtime/outbox runtime/archive runtime/rejected runtime/receipts
podman run --name lr8-nifi -d \
    -p 127.0.0.1:8443:8443 \
    -e SINGLE_USER_CREDENTIALS_USERNAME="$NIFI_USERNAME" \
    -e SINGLE_USER_CREDENTIALS_PASSWORD="$NIFI_PASSWORD" \
    -e NIFI_WEB_PROXY_HOST=localhost:8443,127.0.0.1:8443 \
    -e NIFI_JVM_HEAP_INIT=512m -e NIFI_JVM_HEAP_MAX=1g -e TZ=UTC \
    -v "$PWD/runtime:/opt/nifi/lr8/runtime" \
    -v "$PWD/src:/opt/nifi/lr8/src:ro" \
    -v "$PWD/runtime/jdbc:/opt/nifi/jdbc:ro" \
    -v lr8-nifi-conf:/opt/nifi/nifi-current/conf \
    -v lr8-nifi-content:/opt/nifi/nifi-current/content_repository \
    -v lr8-nifi-flowfile:/opt/nifi/nifi-current/flowfile_repository \
    -v lr8-nifi-provenance:/opt/nifi/nifi-current/provenance_repository \
    -v lr8-nifi-database:/opt/nifi/nifi-current/database_repository \
    -v lr8-nifi-state:/opt/nifi/nifi-current/state \
    -v lr8-nifi-logs:/opt/nifi/nifi-current/logs \
    docker.io/apache/nifi:2.6.0
