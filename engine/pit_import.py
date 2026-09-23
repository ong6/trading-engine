"""Validated, isolated ingestion boundary for licensed point-in-time datasets."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db
from engine.lib.provenance import canonical_sha256

SCHEMA_VERSION = 1
KINDS = frozenset({"security", "price", "fundamental", "membership",
                   "corporate_action", "news"})
REQUIRED_COLUMNS = ("entity_id", "security_id", "event_at", "published_at",
                    "available_at", "payload_json")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_IMPORT_BYTES = 256_000_000


class PitImportError(ValueError):
    """A historical-data manifest or row violates the import contract."""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS pit_import_batches (
        batch_sha256 VARCHAR PRIMARY KEY, schema_version INTEGER NOT NULL,
        dataset_id VARCHAR NOT NULL, vendor VARCHAR NOT NULL, source_version VARCHAR NOT NULL,
        license_id VARCHAR NOT NULL, license_accepted_at TIMESTAMP NOT NULL,
        redistribution_allowed BOOLEAN NOT NULL, manifest_payload VARCHAR NOT NULL,
        file_sha256 VARCHAR NOT NULL, row_count BIGINT NOT NULL, imported_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS pit_import_rows (
        batch_sha256 VARCHAR NOT NULL, row_number BIGINT NOT NULL, dataset_kind VARCHAR NOT NULL,
        entity_id VARCHAR NOT NULL, security_id VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL,
        published_at TIMESTAMP, available_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL,
        payload_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE,
        PRIMARY KEY(batch_sha256,row_number))"""
    )


def _timestamp(raw: str, field: str, *, optional: bool = False) -> datetime | None:
    if optional and raw == "":
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PitImportError(f"{field} is invalid") from exc
    if value.utcoffset() is None:
        raise PitImportError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise PitImportError(f"{field} is invalid")
    return value


def load_manifest(path: Path, data_root: Path) -> tuple[dict, Path, bytes]:
    """Validate one manifest and its exact local source file without writing."""
    try:
        manifest = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise PitImportError("manifest is unreadable") from exc
    required = {"schema_version", "dataset_id", "dataset_kind", "vendor",
                "source_version", "license", "file", "columns"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PitImportError("manifest shape is invalid")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["dataset_kind"] not in KINDS:
        raise PitImportError("manifest version or dataset kind is invalid")
    for field in ("dataset_id", "vendor", "source_version"):
        _identifier(manifest[field], field)
    license_info = manifest["license"]
    if (not isinstance(license_info, dict)
            or set(license_info) != {"id", "accepted_at", "redistribution_allowed"}
            or type(license_info["redistribution_allowed"]) is not bool):
        raise PitImportError("license declaration is invalid")
    _identifier(license_info["id"], "license id")
    _timestamp(license_info["accepted_at"], "license accepted_at")
    file_info = manifest["file"]
    if (not isinstance(file_info, dict) or set(file_info) != {"path", "bytes", "sha256"}
            or isinstance(file_info["bytes"], bool) or not isinstance(file_info["bytes"], int)
            or not 0 < file_info["bytes"] <= MAX_IMPORT_BYTES
            or not isinstance(file_info["sha256"], str)
            or SHA256.fullmatch(file_info["sha256"]) is None):
        raise PitImportError("file declaration is invalid")
    root = data_root.resolve(strict=True)
    relative = Path(file_info["path"])
    if relative.is_absolute():
        raise PitImportError("source file path must be relative")
    candidate = data_root / relative
    if candidate.is_symlink():
        raise PitImportError("source file may not be a symlink")
    try:
        source = candidate.resolve(strict=True)
        source.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PitImportError("source file escapes the import root") from exc
    if not source.is_file():
        raise PitImportError("source file is not regular")
    body = source.read_bytes()
    if len(body) != file_info["bytes"] or hashlib.sha256(body).hexdigest() != file_info["sha256"]:
        raise PitImportError("source file does not match its manifest")
    if manifest["columns"] != list(REQUIRED_COLUMNS):
        raise PitImportError("manifest columns are invalid")
    return manifest, source, body


def _rows(manifest: dict, body: bytes) -> list[dict]:
    try:
        text = body.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
    except UnicodeDecodeError as exc:
        raise PitImportError("source file is not UTF-8") from exc
    if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
        raise PitImportError("source header differs from manifest schema")
    rows, seen = [], set()
    for number, raw in enumerate(reader, 2):
        entity = _identifier(raw["entity_id"], f"row {number} entity_id")
        security = _identifier(raw["security_id"], f"row {number} security_id")
        event = _timestamp(raw["event_at"], f"row {number} event_at")
        published = _timestamp(raw["published_at"], f"row {number} published_at", optional=True)
        available = _timestamp(raw["available_at"], f"row {number} available_at")
        if event > available or (published is not None and (event > published or published > available)):
            raise PitImportError(f"row {number} has impossible point-in-time ordering")
        try:
            payload = json.loads(raw["payload_json"])
        except (TypeError, ValueError) as exc:
            raise PitImportError(f"row {number} payload is invalid") from exc
        if not isinstance(payload, dict):
            raise PitImportError(f"row {number} payload is invalid")
        key = (entity, security, event)
        if key in seen:
            raise PitImportError(f"row {number} duplicates an entity/security/event")
        seen.add(key)
        rows.append({"row_number": number, "dataset_kind": manifest["dataset_kind"],
                     "entity_id": entity, "security_id": security, "event_at": event,
                     "published_at": published, "available_at": available,
                     "payload": payload, "payload_sha256": canonical_sha256(payload)})
    if not rows:
        raise PitImportError("source file has no data rows")
    return rows


def import_manifest(
    con: duckdb.DuckDBPyConnection, manifest_path: Path, data_root: Path, *, imported_at: datetime,
) -> dict:
    manifest, _source, body = load_manifest(manifest_path, data_root)
    rows = _rows(manifest, body)
    accepted = _timestamp(manifest["license"]["accepted_at"], "license accepted_at")
    if type(imported_at) is not datetime or imported_at.utcoffset() is None:
        raise PitImportError("imported_at must include a timezone")
    imported = imported_at.astimezone(timezone.utc).replace(tzinfo=None)
    if accepted > imported:
        raise PitImportError("license acceptance is after import time")
    manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    batch_sha = canonical_sha256({"manifest": manifest, "row_count": len(rows)})
    init_schema(con)
    existing = con.execute(
        "SELECT row_count,manifest_payload FROM pit_import_batches WHERE batch_sha256=?",
        [batch_sha],
    ).fetchone()
    if existing is not None:
        if existing != (len(rows), manifest_payload):
            raise PitImportError("historical import replay differs")
        return {"batch_sha256": batch_sha, "row_count": len(rows), "replayed": True}
    with db.transaction(con):
        con.execute(
            "INSERT INTO pit_import_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [batch_sha, SCHEMA_VERSION, manifest["dataset_id"], manifest["vendor"],
             manifest["source_version"], manifest["license"]["id"], accepted,
             manifest["license"]["redistribution_allowed"], manifest_payload,
             manifest["file"]["sha256"], len(rows), imported],
        )
        for row in rows:
            identity = {"batch_sha256": batch_sha, **{
                key: (value.isoformat() if isinstance(value, datetime) else value)
                for key, value in row.items() if key != "payload"
            }}
            con.execute(
                "INSERT INTO pit_import_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [batch_sha, row["row_number"], row["dataset_kind"], row["entity_id"],
                 row["security_id"], row["event_at"], row["published_at"],
                 row["available_at"], json.dumps(row["payload"], sort_keys=True,
                                                    separators=(",", ":")),
                 row["payload_sha256"], canonical_sha256(identity)],
            )
    return {"batch_sha256": batch_sha, "row_count": len(rows), "replayed": False}


def audit_manifest(manifest_path: Path, data_root: Path) -> dict:
    manifest, source, body = load_manifest(manifest_path, data_root)
    rows = _rows(manifest, body)
    availability = [row["available_at"] for row in rows]
    securities = {row["security_id"] for row in rows}
    return {
        "status": "valid", "dataset_id": manifest["dataset_id"],
        "dataset_kind": manifest["dataset_kind"], "vendor": manifest["vendor"],
        "source_version": manifest["source_version"], "license_id": manifest["license"]["id"],
        "redistribution_allowed": manifest["license"]["redistribution_allowed"],
        "source_path": str(source), "source_bytes": len(body), "row_count": len(rows),
        "security_count": len(securities), "available_start": min(availability).isoformat(),
        "available_end": max(availability).isoformat(),
        "operational_tables_mutated": False, "strategy_authority": "none",
    }
