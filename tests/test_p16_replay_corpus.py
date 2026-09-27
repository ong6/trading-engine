"""W4 content, checkpoint, capture, and as-of corpus tests."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from farm.replay.corpus import (
    capture_sha256,
    deduplicate_visible_headlines,
    facts_as_of,
    latest_completed_cursor,
    put_content_object,
    record_task_attempt,
    validate_capture,
)
from farm.replay.store import ReplayStoreError, open_store

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)


def _store(tmp_path):
    root = tmp_path / "research"
    root.mkdir()
    live = tmp_path / "live.duckdb"
    live.touch()
    return root, live, root / "catalog.duckdb"


def test_content_object_is_atomic_content_addressed_and_replay_exact(tmp_path):
    root, _live, _db = _store(tmp_path)
    first = put_content_object(root, source="ccnews", payload=b"body", suffix=".warc")
    assert first == put_content_object(root, source="ccnews", payload=b"body", suffix=".warc")
    assert hashlib.sha256(b"body").hexdigest() == first["sha256"]
    assert not list(root.rglob("*.partial"))


def test_failed_or_truncated_attempt_never_advances_cursor(tmp_path):
    root, live, target = _store(tmp_path)
    with open_store(target, research_root=root, live_db_path=live, kind="catalog") as con:
        record_task_attempt(
            con,
            task_key="gdelt:2024-01",
            attempt=1,
            status="failed",
            cursor_before=None,
            cursor_after=None,
            receipt_sha256=None,
            recorded_at=NOW,
        )
        assert latest_completed_cursor(con, "gdelt:2024-01", 1) is None
        with pytest.raises(ReplayStoreError, match="advanced_cursor"):
            record_task_attempt(
                con,
                task_key="gdelt:2024-01",
                attempt=2,
                status="truncated",
                cursor_before=None,
                cursor_after="page-2",
                receipt_sha256=None,
                recorded_at=NOW,
            )
        record_task_attempt(
            con,
            task_key="gdelt:2024-01",
            attempt=2,
            status="completed",
            cursor_before=None,
            cursor_after="page-2",
            receipt_sha256="a" * 64,
            recorded_at=NOW,
        )
        assert latest_completed_cursor(con, "gdelt:2024-01", 2) == "page-2"


def test_capture_binds_archive_payload_digest_and_extractor_version():
    body = b"captured body"
    row = {
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "archive_payload_digest": "sha1:ARCHIVE",
        "extractor_version": "warc-body-v1",
    }
    row["capture_sha256"] = capture_sha256(
        row["archive_payload_digest"], row["extractor_version"]
    )
    validate_capture(row, body)
    with pytest.raises(ReplayStoreError, match="body_digest"):
        validate_capture(row, body + b" changed")
    with pytest.raises(ReplayStoreError, match="archive_identity"):
        validate_capture({**row, "extractor_version": "warc-body-v2"}, body)


def test_asof_facts_choose_latest_visible_revision_without_rewriting_real_time():
    rows = [
        {
            "fact_id": "f1",
            "revision": 1,
            "available_at_replay": "2024-01-02T12:00:00Z",
            "retrieved_at_real": "2026-09-27T12:00:00Z",
            "value": "first",
        },
        {
            "fact_id": "f1",
            "revision": 2,
            "available_at_replay": "2024-01-03T12:00:00Z",
            "retrieved_at_real": "2026-09-27T12:01:00Z",
            "value": "later",
        },
    ]
    first = facts_as_of(rows, datetime(2024, 1, 2, 13, tzinfo=timezone.utc))
    assert first[0]["value"] == "first"
    assert first[0]["retrieved_at_real"].startswith("2026-")
    assert facts_as_of(rows, datetime(2024, 1, 3, 13, tzinfo=timezone.utc))[0][
        "value"
    ] == "later"


def test_dedup_anchors_48_hours_on_first_visible_copy():
    def row(source_id, available, event):
        return {
            "source": "fixture",
            "source_id": source_id,
            "language": "en",
            "headline": "Same  headline",
            "available_at_replay": available,
            "event_at": event,
        }

    rows = [
        row("a", "2024-01-01T01:00:00Z", "2024-01-01T00:00:00Z"),
        row("b", "2024-01-02T01:00:00Z", "2024-01-02T00:00:00Z"),
        row("c", "2024-01-03T02:00:00Z", "2024-01-03T01:00:00Z"),
        row("future", "2024-01-05T00:00:00Z", "2024-01-01T00:00:00Z"),
    ]
    kept = deduplicate_visible_headlines(
        rows, datetime(2024, 1, 4, tzinfo=timezone.utc)
    )
    assert [item["source_id"] for item in kept] == ["a", "c"]


def test_naive_availability_is_rejected():
    with pytest.raises(ReplayStoreError, match="naive_corpus_clock"):
        facts_as_of(
            [{"fact_id": "f", "revision": 1, "available_at_replay": "2024-01-01"}],
            NOW,
        )
