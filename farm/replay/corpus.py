"""Content-addressed W4 corpus primitives; all network access is injected elsewhere."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from engine.lib.provenance import canonical_sha256
from farm.replay.store import ReplayStoreError, append_exact, load_record

_NAME = re.compile(r"[a-z0-9_-]+")


def _instant(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ReplayStoreError("naive_corpus_clock")
    return parsed.astimezone(timezone.utc)


def put_content_object(root: Path, *, source: str, payload: bytes, suffix: str) -> dict:
    if not root.is_absolute() or _NAME.fullmatch(source) is None or not suffix.startswith("."):
        raise ReplayStoreError("invalid_content_object_path")
    digest = hashlib.sha256(payload).hexdigest()
    destination = root / "receipts" / source / digest[:2] / f"{digest}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ReplayStoreError("content_object_hash_conflict")
        return {"sha256": digest, "bytes": len(payload), "path": str(destination)}
    fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", suffix=".partial", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() != payload:
                raise ReplayStoreError("content_object_hash_conflict")
        os.unlink(temporary)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"sha256": digest, "bytes": len(payload), "path": str(destination)}


def capture_sha256(archive_payload_digest: str, extractor_version: str) -> str:
    if not archive_payload_digest or not extractor_version:
        raise ReplayStoreError("capture_identity_incomplete")
    return canonical_sha256(
        {
            "archive_payload_digest": archive_payload_digest,
            "extractor_version": extractor_version,
        }
    )


def validate_capture(row: Mapping, body: bytes) -> None:
    if hashlib.sha256(body).hexdigest() != row.get("body_sha256"):
        raise ReplayStoreError("capture_body_digest_mismatch")
    expected = capture_sha256(
        str(row.get("archive_payload_digest", "")), str(row.get("extractor_version", ""))
    )
    if row.get("capture_sha256") != expected:
        raise ReplayStoreError("capture_archive_identity_mismatch")


def record_task_attempt(
    con,
    *,
    task_key: str,
    attempt: int,
    status: str,
    cursor_before: str | None,
    cursor_after: str | None,
    receipt_sha256: str | None,
    recorded_at: datetime,
) -> str:
    if attempt < 1 or status not in {"completed", "failed", "truncated"}:
        raise ReplayStoreError("invalid_ingestion_attempt")
    if status != "completed" and cursor_after is not None:
        raise ReplayStoreError("failed_attempt_advanced_cursor")
    payload = {
        "task_key": task_key,
        "attempt": attempt,
        "status": status,
        "cursor_before": cursor_before,
        "cursor_after": cursor_after,
        "receipt_sha256": receipt_sha256,
    }
    attempt_sha = append_exact(
        con,
        record_type="ingestion_attempt",
        record_key=f"{task_key}:{attempt}",
        payload=payload,
        recorded_at=recorded_at,
    )
    if status == "completed":
        append_exact(
            con,
            record_type="ingestion_cursor",
            record_key=f"{task_key}:{attempt}",
            payload={"task_key": task_key, "attempt": attempt, "cursor": cursor_after},
            recorded_at=recorded_at,
        )
    return attempt_sha


def latest_completed_cursor(con, task_key: str, through_attempt: int) -> str | None:
    for attempt in range(through_attempt, 0, -1):
        row = load_record(con, "ingestion_cursor", f"{task_key}:{attempt}")
        if row is not None:
            return row["payload"]["cursor"]
    return None


def facts_as_of(rows: Sequence[Mapping], cutoff: datetime) -> list[dict]:
    if cutoff.tzinfo is None:
        raise ReplayStoreError("naive_fact_cutoff")
    cutoff = cutoff.astimezone(timezone.utc)
    selected = {}
    for source in rows:
        available = _instant(source["available_at_replay"])
        if available > cutoff:
            continue
        key = str(source["fact_id"])
        rank = (available, int(source["revision"]))
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, dict(source))
    return [selected[key][1] for key in sorted(selected)]


def deduplicate_visible_headlines(rows: Sequence[Mapping], cutoff: datetime) -> list[dict]:
    cutoff = _instant(cutoff)
    visible = [row for row in rows if _instant(row["available_at_replay"]) <= cutoff]
    visible.sort(key=lambda row: (row["available_at_replay"], row["source"], row["source_id"]))
    anchors, kept = {}, []
    for source in visible:
        headline = " ".join(unicodedata.normalize("NFKC", str(source["headline"])).casefold().split())
        key = (str(source.get("language", "und")), headline)
        event_at = _instant(source["event_at"])
        anchor = anchors.get(key)
        if anchor is None or event_at - anchor > timedelta(hours=48):
            anchors[key] = event_at
            kept.append(dict(source))
    return kept
