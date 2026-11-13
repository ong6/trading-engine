"""Raw-payload read paths of main at 1fae615d, vendored verbatim for rollback compatibility.

Sources: tools/free_sources.py (_parse_massive_cache_receipt, _massive_cache_receipt,
_massive_cache) and tools/free_massive_options.py (the file read in _cached_body). Main reads
only plain ``<sha>.json`` files: it opens the named file and checks its SHA-256. Do not edit
these bodies; they stand for the code a rollback runs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from engine import free_sources


def _parse_massive_cache_receipt(receipt_path, session_date):
    try:
        receipt = json.loads(receipt_path.read_text())
        if set(receipt) != {"date", "fetched_at", "raw_file", "source_sha256"}:
            raise ValueError
        if receipt["date"] != session_date.isoformat():
            raise ValueError
        source_sha = receipt["source_sha256"]
        if free_sources.SHA256.fullmatch(source_sha) is None:
            raise ValueError
        if receipt["raw_file"] != f"{source_sha}.json":
            raise ValueError
        fetched_at = datetime.fromisoformat(receipt["fetched_at"])
        if fetched_at.utcoffset() is None:
            raise ValueError
    except (OSError, TypeError, ValueError) as exc:
        raise free_sources.FreeSourceError("Massive cache receipt is invalid") from exc
    return receipt, fetched_at, source_sha


def _massive_cache_receipt(
    data_dir: Path, session_date: date,
) -> tuple[Path, datetime, str] | None:
    directory = data_dir / "massive" / session_date.isoformat()
    receipt_path = directory / "receipt.json"
    if not receipt_path.exists():
        if directory.exists() and any(directory.iterdir()):
            raise free_sources.FreeSourceError("Massive date cache is incomplete")
        return None
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise free_sources.FreeSourceError("Massive cache receipt is unsafe")
    receipt, fetched_at, source_sha = _parse_massive_cache_receipt(receipt_path, session_date)
    raw_path = directory / receipt["raw_file"]
    if raw_path.is_symlink() or not raw_path.is_file():
        raise free_sources.FreeSourceError("Massive cached response is missing or unsafe")
    return raw_path, fetched_at, source_sha


def massive_cache(data_dir: Path, session_date: date) -> tuple[bytes, datetime] | None:
    receipt = _massive_cache_receipt(data_dir, session_date)
    if receipt is None:
        return None
    raw_path, fetched_at, source_sha = receipt
    body = raw_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != source_sha:
        raise free_sources.FreeSourceError("Massive cached response hash is invalid")
    free_sources.parse_massive_grouped_daily(body, session_date)
    return body, fetched_at


def hash_named_payload(directory: Path, source_sha: str) -> bytes:
    """The read every other main writer's reader performs: ``<sha>.json``, hash-checked."""
    raw = (directory / f"{source_sha}.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != source_sha:
        raise free_sources.FreeSourceError("cached response hash is invalid")
    return raw
