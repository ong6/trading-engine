"""Immutable migration modules and compatibility API."""

from engine.lib import snapshots as _snapshots

CURRENT_SCHEMA_ID = _snapshots.CURRENT_SCHEMA_ID
MIGRATION_MODULES = _snapshots.MIGRATION_MODULES
MIGRATION_TABLE = _snapshots.MIGRATION_TABLE
MINIMUM_SCHEMA_ID = _snapshots.MINIMUM_SCHEMA_ID
Migration = _snapshots.Migration
SchemaIdentityError = _snapshots.SchemaIdentityError
catalog = _snapshots.catalog
catalog_sha256 = _snapshots.catalog_sha256
database_name = _snapshots.database_name
records = _snapshots.migration_records
migrations = _snapshots.migrations
schema_id = _snapshots.recorded_schema_id
require_compatible_schema = _snapshots.require_compatible_schema
sequence_state = _snapshots.sequence_state

__all__ = (
    "CURRENT_SCHEMA_ID", "MIGRATION_MODULES", "MIGRATION_TABLE", "MINIMUM_SCHEMA_ID",
    "Migration", "SchemaIdentityError", "catalog", "catalog_sha256", "database_name",
    "migrations", "records", "require_compatible_schema", "schema_id", "sequence_state",
)
