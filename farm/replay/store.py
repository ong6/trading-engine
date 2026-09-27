"""Explicit, isolated and append-only stores for P16 historical replay."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT

STORE_KINDS = frozenset({"catalog", "control", "replay"})


class ReplayStoreError(ValueError):
    """A store path or append violated the W4 evidence contract."""


def checked_store_path(
    path: Path, *, research_root: Path, live_db_path: Path
) -> Path:
    if not path.is_absolute() or not research_root.is_absolute() or not live_db_path.is_absolute():
        raise ReplayStoreError("store_paths_must_be_absolute")
    if research_root.is_symlink():
        raise ReplayStoreError("research_root_must_not_be_symlink")
    root = research_root.resolve()
    checkout = REPO_ROOT.resolve()
    target = path.resolve(strict=False)
    live = live_db_path.resolve(strict=False)
    if root == checkout or root.is_relative_to(checkout):
        raise ReplayStoreError("research_root_inside_checkout")
    if target == root or not target.is_relative_to(root):
        raise ReplayStoreError("store_outside_research_root")
    current = path
    while current != research_root:
        if current.exists() and current.is_symlink():
            raise ReplayStoreError("store_path_contains_symlink")
        current = current.parent
        if current == current.parent and current != research_root:
            raise ReplayStoreError("store_outside_research_root")
    if target == live:
        raise ReplayStoreError("live_database_forbidden")
    if path.exists() and live_db_path.exists():
        target_stat, live_stat = path.stat(), live_db_path.stat()
        if (target_stat.st_dev, target_stat.st_ino) == (live_stat.st_dev, live_stat.st_ino):
            raise ReplayStoreError("live_database_inode_forbidden")
    return target


def _iso(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ReplayStoreError("recorded_at_must_be_timezone_aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _init_schema(con, kind: str) -> None:
    if kind not in STORE_KINDS:
        raise ReplayStoreError("invalid_store_kind")
    con.execute(
        """CREATE TABLE IF NOT EXISTS w4_store_identity (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
            store_kind VARCHAR NOT NULL)"""
    )
    existing = con.execute("SELECT store_kind FROM w4_store_identity").fetchone()
    if existing is None:
        con.execute("INSERT INTO w4_store_identity VALUES (TRUE, ?)", [kind])
    elif existing[0] != kind:
        raise ReplayStoreError("store_kind_conflict")
    con.execute(
        """CREATE TABLE IF NOT EXISTS w4_evidence_records (
            record_type VARCHAR NOT NULL,
            record_key VARCHAR NOT NULL,
            payload_sha256 VARCHAR NOT NULL,
            payload_json VARCHAR NOT NULL,
            recorded_at VARCHAR NOT NULL,
            PRIMARY KEY(record_type, record_key))"""
    )


@contextmanager
def open_store(
    path: Path,
    *,
    research_root: Path,
    live_db_path: Path,
    kind: str,
    read_only: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    target = checked_store_path(
        path, research_root=research_root, live_db_path=live_db_path
    )
    if not read_only:
        target.parent.mkdir(parents=True, exist_ok=True)
    con = engine_db.connect(target, read_only=read_only)
    try:
        if not read_only:
            _init_schema(con, kind)
        else:
            row = con.execute("SELECT store_kind FROM w4_store_identity").fetchone()
            if row is None or row[0] != kind:
                raise ReplayStoreError("store_kind_conflict")
        yield con
    finally:
        con.close()


def append_exact(
    con,
    *,
    record_type: str,
    record_key: str,
    payload: Mapping,
    recorded_at: datetime,
) -> str:
    if not record_type or not record_key:
        raise ReplayStoreError("empty_record_identity")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_sha256 = canonical_sha256(payload)
    timestamp = _iso(recorded_at)
    existing = con.execute(
        "SELECT payload_sha256, payload_json, recorded_at FROM w4_evidence_records "
        "WHERE record_type=? AND record_key=?",
        [record_type, record_key],
    ).fetchone()
    if existing is not None:
        if existing == (payload_sha256, encoded, timestamp):
            return payload_sha256
        raise ReplayStoreError("immutable_record_conflict")
    con.execute(
        "INSERT INTO w4_evidence_records VALUES (?,?,?,?,?)",
        [record_type, record_key, payload_sha256, encoded, timestamp],
    )
    return payload_sha256


def load_record(con, record_type: str, record_key: str) -> dict | None:
    row = con.execute(
        "SELECT payload_sha256, payload_json, recorded_at FROM w4_evidence_records "
        "WHERE record_type=? AND record_key=?",
        [record_type, record_key],
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row[1])
    return {"payload_sha256": row[0], "payload": payload, "recorded_at": row[2]}
