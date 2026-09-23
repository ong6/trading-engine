"""Vendor-neutral PIT manifest and isolated import tests."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from engine import pit_import

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
HEADER = "entity_id,security_id,event_at,published_at,available_at,payload_json\n"
ROW = 'issuer-1,security-1,2022-01-01T00:00:00Z,2022-02-01T14:30:00Z,2022-02-01T14:30:01Z,"{""value"":1}"\n'


def _fixture(root, *, row=ROW):
    source = root / "vendor.csv"
    source.write_text(HEADER + row)
    manifest = {
        "schema_version": 1, "dataset_id": "vendor-fundamentals-v1",
        "dataset_kind": "fundamental", "vendor": "example-vendor",
        "source_version": "2026-09",
        "revision_semantics": "vendor_revisions_preserved",
        "availability_policy": "available_at is the first licensed delivery timestamp",
        "coverage": {"event_start": "2022-01-01T00:00:00Z",
                     "event_end": "2022-01-01T00:00:00Z",
                     "security_count": 1, "row_count": 1},
        "license": {"id": "research-license-v1",
                    "accepted_at": "2026-09-01T00:00:00Z",
                    "redistribution_allowed": False},
        "file": {"path": source.name, "bytes": source.stat().st_size,
                 "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "columns": list(pit_import.REQUIRED_COLUMNS),
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, source


def test_manifest_audit_and_apply_are_isolated_and_replay_stable(con, tmp_path, capsys):
    manifest, _source = _fixture(tmp_path)
    audit = pit_import.audit_manifest(manifest, tmp_path)
    assert audit["status"] == "valid" and audit["row_count"] == 1
    assert audit["operational_tables_mutated"] is False
    first = pit_import.import_manifest(con, manifest, tmp_path, imported_at=NOW)
    second = pit_import.import_manifest(con, manifest, tmp_path, imported_at=NOW)
    assert first["replayed"] is False and second["replayed"] is True
    assert con.execute("SELECT COUNT(*) FROM pit_import_rows").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM prices").fetchone() == (0,)
    con.execute("DELETE FROM pit_import_rows")
    with pytest.raises(pit_import.PitImportError, match="replay differs"):
        pit_import.import_manifest(con, manifest, tmp_path, imported_at=NOW)
    database = tmp_path / "audit.duckdb"
    assert pit_import.main([str(manifest), "--data-root", str(tmp_path),
                            "--database", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "audit"
    assert not database.exists()


def test_manifest_rejects_checksum_drift_and_impossible_times(tmp_path):
    manifest, source = _fixture(tmp_path)
    source.write_text(HEADER + ROW.replace('""value"":1', '""value"":2'))
    with pytest.raises(pit_import.PitImportError, match="does not match"):
        pit_import.audit_manifest(manifest, tmp_path)
    manifest, source = _fixture(
        tmp_path, row=ROW.replace("2022-02-01T14:30:01Z", "2022-01-31T14:30:01Z")
    )
    with pytest.raises(pit_import.PitImportError, match="ordering"):
        pit_import.audit_manifest(manifest, tmp_path)


def test_manifest_rejects_source_symlink(tmp_path):
    manifest, source = _fixture(tmp_path)
    real = tmp_path / "real.csv"
    source.rename(real)
    source.symlink_to(real)
    with pytest.raises(pit_import.PitImportError, match="symlink"):
        pit_import.audit_manifest(manifest, tmp_path)


def test_manifest_rejects_coverage_drift(tmp_path):
    manifest, _source = _fixture(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["coverage"]["row_count"] = 2
    manifest.write_text(json.dumps(payload))
    with pytest.raises(pit_import.PitImportError, match="coverage differs"):
        pit_import.audit_manifest(manifest, tmp_path)
