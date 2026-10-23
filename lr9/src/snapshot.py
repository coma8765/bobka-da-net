import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from psycopg import sql

MARKER = "Managed by LR9 benchmark; disposable copy"


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def container_command(config, *arguments):
    return [
        "podman",
        "exec",
        "-i",
        "--env",
        "PGPASSWORD",
        config.postgres_container,
        *arguments,
    ]


def run_container(config, *arguments, **kwargs):
    return subprocess.run(
        container_command(config, *arguments),
        env={**os.environ, "PGPASSWORD": config.password},
        check=True,
        **kwargs,
    )


@contextmanager
def exclusive_target(config):
    config.validate_target()
    with config.connect("postgres") as admin:
        locked = admin.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (config.database,)
        ).fetchone()[0]
        if not locked:
            raise RuntimeError("Another LR9 process is using this target database")
        try:
            yield
        finally:
            admin.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (config.database,))


def check_container_server(config):
    """Refuse to mix a host connection with dump tools from another server."""
    with config.connect("postgres") as connection:
        host_id = str(
            connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]
        )
    result = run_container(
        config,
        "psql",
        "-U",
        config.user,
        "-d",
        "postgres",
        "-Atc",
        "SELECT system_identifier FROM pg_control_system()",
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != host_id:
        raise ValueError("PostgreSQL container and PGHOST refer to different servers")


def create_snapshot(config, path):
    path = Path(path)
    config.validate_target()
    check_container_server(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        try:
            run_container(
                config,
                "pg_dump",
                "-U",
                config.user,
                "-d",
                config.source_database,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                stdout=stream,
            )
        except BaseException:
            path.unlink()
            raise
    metadata = {
        "sha256": file_hash(path),
        "source_database": config.source_database,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def restore_snapshot(config, path):
    """Caller holds exclusive_target for the entire restore/use lifecycle."""
    config.validate_target()
    path = Path(path)
    metadata = json.loads(path.with_suffix(".json").read_text())
    if file_hash(path) != metadata["sha256"]:
        raise ValueError("Snapshot checksum mismatch")
    check_container_server(config)
    with config.connect("postgres") as admin:
        row = admin.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (config.database,),
        ).fetchone()
        if row:
            if row[0] != MARKER:
                raise ValueError("Existing target is not marked as an LR9 disposable database")
            # No FORCE: another open session prevents accidental interruption.
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(config.database)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config.database)))
        admin.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(config.database),
                sql.Literal(MARKER),
            )
        )
    with path.open("rb") as stream:
        run_container(
            config,
            "pg_restore",
            "-U",
            config.user,
            "-d",
            config.database,
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            stdin=stream,
            stdout=subprocess.DEVNULL,
        )
    with config.connect() as connection:
        # LR5 adds one document for every delivery and prevents every DELETE.
        # Only the disposable target is prepared; keep its FK and all LR1 data.
        if (
            connection.execute("SELECT to_regclass('lr5.delivery_documents')").fetchone()[0]
            is not None
        ):
            connection.execute("TRUNCATE lr5.delivery_documents")
        connection.execute("ANALYZE")
    metadata["target_preparation"] = (
        "After restoring the complete dump, empty lr5.delivery_documents if present; "
        "preserve its FK, all LR1 rows/sequences and other schemas. ANALYZE."
    )
    return metadata


def image_metadata(config):
    result = {}
    for name in (config.postgres_container, config.redis_container):
        container = subprocess.run(
            ["podman", "inspect", name, "--format", "{{.Image}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        image = subprocess.run(
            ["podman", "image", "inspect", container, "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        info = json.loads(image.stdout)[0]
        result[name] = {
            "id": container,
            "digest": info.get("Digest", ""),
            "names": info.get("RepoTags", []),
        }
    return result
