"""Cycle-safe operational schema identity and immutable migration registry."""
from __future__ import annotations

import hashlib
import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import duckdb

from engine.lib.provenance import canonical_sha256

MIGRATION_TABLE = "schema_migrations"
MIGRATION_MODULES = (
    "engine.migrations.0000_post_r15_baseline",
    "engine.migrations.0001_generation_storage",
)
CURRENT_SCHEMA_ID = len(MIGRATION_MODULES) - 1
MINIMUM_SCHEMA_ID = 0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class SchemaIdentityError(RuntimeError):
    """The database schema identity is missing, malformed, or incompatible."""


@dataclass(frozen=True)
class Migration:
    migration_id: int
    description: str
    sha256: str
    statements: tuple[str, ...]
    module: ModuleType


def _module_migration(name: str) -> Migration:
    module = importlib.import_module(name)
    source = Path(module.__file__ or "").read_bytes()
    migration_id = getattr(module, "MIGRATION_ID", None)
    description = getattr(module, "DESCRIPTION", None)
    statements = getattr(module, "STATEMENTS", None)
    if (
        type(migration_id) is not int
        or not isinstance(description, str)
        or not description
        or not isinstance(statements, tuple)
        or any(not isinstance(statement, str) or not statement.strip() for statement in statements)
    ):
        raise SchemaIdentityError(f"invalid migration module: {name}")
    return Migration(
        migration_id=migration_id,
        description=description,
        sha256=hashlib.sha256(source).hexdigest(),
        statements=statements,
        module=module,
    )


def migrations() -> tuple[Migration, ...]:
    loaded = tuple(_module_migration(name) for name in MIGRATION_MODULES)
    if tuple(item.migration_id for item in loaded) != tuple(range(len(loaded))):
        raise SchemaIdentityError("migration IDs must be contiguous from zero")
    return loaded


def database_name(con: duckdb.DuckDBPyConnection) -> str:
    return str(con.execute("SELECT current_database()").fetchone()[0])


def catalog(con: duckdb.DuckDBPyConnection) -> dict:
    """Stable schema identity; sequence position is deliberately separate."""
    database = database_name(con)
    return {
        "tables": con.execute(
            "SELECT schema_name, table_name, sql FROM duckdb_tables() "
            "WHERE database_name=? AND NOT internal AND NOT temporary "
            "AND table_name<>? ORDER BY schema_name, table_name",
            [database, MIGRATION_TABLE],
        ).fetchall(),
        "views": con.execute(
            "SELECT schema_name, view_name, sql FROM duckdb_views() "
            "WHERE database_name=? AND NOT internal AND NOT temporary "
            "ORDER BY schema_name, view_name", [database],
        ).fetchall(),
        "indexes": con.execute(
            "SELECT schema_name, index_name, table_name, is_unique, is_primary, sql "
            "FROM duckdb_indexes() WHERE database_name=? AND table_name<>? "
            "ORDER BY schema_name, index_name", [database, MIGRATION_TABLE],
        ).fetchall(),
        "sequences": con.execute(
            "SELECT schema_name, sequence_name, min_value, max_value, increment_by, cycle "
            "FROM duckdb_sequences() WHERE database_name=? "
            "AND NOT temporary ORDER BY schema_name, sequence_name", [database],
        ).fetchall(),
    }


def catalog_sha256(con: duckdb.DuckDBPyConnection) -> str:
    return canonical_sha256(catalog(con))


def sequence_state(
    con: duckdb.DuckDBPyConnection, database: str | None = None,
) -> list[dict]:
    """Return runtime sequence positions without folding them into schema identity."""
    database = database_name(con) if database is None else database
    rows = con.execute(
        "SELECT schema_name, sequence_name, min_value, max_value, increment_by, cycle, sql "
        "FROM duckdb_sequences() "
        "WHERE database_name=? AND NOT temporary ORDER BY schema_name, sequence_name",
        [database],
    ).fetchall()
    state = []
    for schema, name, minimum, maximum, increment, cycle, sql in rows:
        match = re.search(r"\bSTART\s+(-?\d+)\b", sql)
        if match is None:
            raise SchemaIdentityError(f"sequence next value is unavailable: {schema}.{name}")
        state.append({
            "schema": schema, "name": name, "min_value": minimum,
            "max_value": maximum, "increment_by": increment, "cycle": cycle,
            "next_value": int(match.group(1)),
        })
    return state


def _has_ledger(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?", [MIGRATION_TABLE],
    ).fetchone() is not None


def records(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    if not _has_ledger(con):
        return []
    try:
        return con.execute(
            f"SELECT migration_id, migration_sha256, source_commit, "
            f"pre_catalog_sha256, post_catalog_sha256, recovery_manifest_sha256 "
            f"FROM {MIGRATION_TABLE} ORDER BY migration_id"
        ).fetchall()
    except duckdb.Error as exc:
        raise SchemaIdentityError("schema migration ledger has an invalid shape") from exc


def schema_id(con: duckdb.DuckDBPyConnection) -> int | None:
    rows = records(con)
    return None if not rows else int(rows[-1][0])


def require_compatible_schema(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum: int = MINIMUM_SCHEMA_ID,
    maximum: int = CURRENT_SCHEMA_ID,
) -> dict:
    """Verify exact migrations, source identities, catalog chain, and current catalog."""
    expected = migrations()
    rows = records(con)
    if not rows:
        raise SchemaIdentityError("database has no recorded operational schema migration")
    ids = tuple(int(row[0]) for row in rows)
    if ids != tuple(range(len(rows))) or ids[-1] >= len(expected):
        raise SchemaIdentityError("database migration history is not supported")
    for index, (row, migration) in enumerate(zip(rows, expected, strict=False)):
        if row[1] != migration.sha256:
            raise SchemaIdentityError(
                f"database migration {migration.migration_id:04d} hash does not match source"
            )
        if not isinstance(row[2], str) or _GIT_SHA.fullmatch(row[2]) is None:
            raise SchemaIdentityError("database migration source commit is invalid")
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in row[3:]
        ):
            raise SchemaIdentityError("database migration history contains an invalid hash")
        if index and row[3] != rows[index - 1][4]:
            raise SchemaIdentityError("database migration catalog chain is broken")
        expected_post = getattr(migration.module, "EXPECTED_CATALOG_SHA256", None)
        if expected_post is not None and row[4] != expected_post:
            raise SchemaIdentityError(
                f"database migration {migration.migration_id:04d} catalog does not match source"
            )
    current = ids[-1]
    if not minimum <= current <= maximum:
        raise SchemaIdentityError(
            f"database schema ID {current} is outside supported range {minimum}..{maximum}"
        )
    current_hash = catalog_sha256(con)
    if rows[-1][4] != current_hash:
        raise SchemaIdentityError("database catalog changed outside the migration sequence")
    return {"database_schema_id": current, "catalog_sha256": current_hash}
