"""Tests for schedule-aware Friday postflight receipt projection."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from server import file_utils, friday_postflight


def _receipt(status="current") -> dict:
    result = {
        "schema_version": 1,
        "checked_at": "2026-09-12T05:15:05+00:00",
        "status": status,
        "expected_date": "2026-09-11",
    }
    if status == "failed":
        result["reason"] = "canonical miner cohort is not current at 4/4"
    else:
        result.update(
            market_date="2026-09-11",
            nightly_started_at="2026-09-11T22:30:01+00:00",
            nightly_finished_at="2026-09-12T00:30:01+00:00",
            miner_job_ids={
                kind: index
                for index, kind in enumerate(sorted(friday_postflight.EXPECTED_MINERS), start=476)
            },
            miner_evidence_at={
                kind: "2026-09-12T00:29:59+00:00" for kind in friday_postflight.EXPECTED_MINERS
            },
        )
    return result


def _write(path, payload):
    path.write_text(json.dumps(payload))


def test_missing_receipt_is_neutral_before_first_run_and_during_grace(tmp_path):
    path = tmp_path / "receipt.json"

    assert friday_postflight.status(path, now=datetime(2026, 9, 11, 12, tzinfo=timezone.utc)) == {
        "status": "not-yet-run",
        "next_expected_at": "2026-09-12T05:15:00+00:00",
    }
    assert friday_postflight.status(
        path, now=datetime(2026, 9, 12, 5, 20, tzinfo=timezone.utc)
    ) == {
        "status": "updating",
        "expected_date": "2026-09-11",
        "expected_at": "2026-09-12T05:15:00+00:00",
    }


def test_missing_receipt_is_overdue_after_grace(tmp_path):
    assert friday_postflight.status(
        tmp_path / "missing.json",
        now=datetime(2026, 9, 12, 5, 30, tzinfo=timezone.utc),
    ) == {
        "status": "overdue",
        "expected_date": "2026-09-11",
        "expected_at": "2026-09-12T05:15:00+00:00",
    }


@pytest.mark.parametrize("receipt_status", ["current", "failed"])
def test_current_slot_receipt_is_projected(tmp_path, receipt_status):
    path = tmp_path / "receipt.json"
    payload = _receipt(receipt_status)
    _write(path, payload)

    assert (
        friday_postflight.status(path, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc))
        == payload
    )


def test_previous_receipt_is_updating_then_stale_at_next_slot(tmp_path):
    path = tmp_path / "receipt.json"
    _write(path, _receipt())

    updating = friday_postflight.status(path, now=datetime(2026, 9, 19, 5, 20, tzinfo=timezone.utc))
    stale = friday_postflight.status(path, now=datetime(2026, 9, 19, 5, 30, tzinfo=timezone.utc))

    assert updating == {
        "status": "updating",
        "expected_date": "2026-09-18",
        "expected_at": "2026-09-19T05:15:00+00:00",
        "previous_status": "current",
    }
    assert stale == {
        "status": "stale",
        "expected_date": "2026-09-18",
        "expected_at": "2026-09-19T05:15:00+00:00",
        "observed_expected_date": "2026-09-11",
        "checked_at": "2026-09-12T05:15:05+00:00",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version=2),
        lambda payload: payload.update(schema_version=True),
        lambda payload: payload.update(unexpected=True),
        lambda payload: payload.pop("market_date"),
        lambda payload: payload.update(checked_at="2026-09-12T05:14:59+00:00"),
        lambda payload: payload.update(expected_date="2026-09-10"),
        lambda payload: payload.update(status="failed", reason="x" * 1_001),
        lambda payload: payload["miner_job_ids"].update(fundamentals=True),
        lambda payload: payload["miner_job_ids"].update(
            fundamentals=payload["miner_job_ids"]["earnings"]
        ),
        lambda payload: payload["miner_evidence_at"].update(
            fundamentals="2026-09-12T00:31:00+00:00"
        ),
    ],
)
def test_malformed_receipt_fails_closed(tmp_path, mutation):
    path = tmp_path / "receipt.json"
    payload = _receipt()
    mutation(payload)
    _write(path, payload)

    assert friday_postflight.status(
        path, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc)
    ) == {"status": "invalid", "reason": "receipt-invalid"}


def test_failed_receipt_rejects_fields_from_current_shape(tmp_path):
    path = tmp_path / "receipt.json"
    payload = _receipt()
    payload.update(status="failed", reason="verification failed")
    _write(path, payload)

    assert friday_postflight.status(
        path, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc)
    ) == {"status": "invalid", "reason": "receipt-invalid"}


@pytest.mark.parametrize("dangling", [False, True])
def test_symlinked_receipt_fails_closed(tmp_path, dangling):
    target = tmp_path / "target.json"
    if not dangling:
        _write(target, _receipt())
    path = tmp_path / "receipt.json"
    path.symlink_to(target)

    assert friday_postflight.status(
        path, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc)
    ) == {"status": "invalid", "reason": "receipt-invalid"}


def test_nonregular_receipt_fails_closed(tmp_path):
    path = tmp_path / "receipt.json"
    path.mkdir()

    assert friday_postflight.status(
        path, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc)
    ) == {"status": "invalid", "reason": "receipt-invalid"}


def test_receipt_below_symlinked_parent_fails_closed(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    _write(target / "receipt.json", _receipt())
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    assert friday_postflight.status(
        alias / "receipt.json",
        now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc),
    ) == {"status": "invalid", "reason": "receipt-invalid"}


def test_receipt_below_dangling_symlinked_parent_fails_closed(tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "missing", target_is_directory=True)

    assert friday_postflight.status(
        alias / "receipt.json",
        now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc),
    ) == {"status": "invalid", "reason": "receipt-invalid"}


def test_receipt_parent_removed_during_load_fails_closed_as_invalid(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    path = parent / "receipt.json"
    _write(path, _receipt())
    displaced = tmp_path / "displaced"
    original = file_utils._read_bounded
    removed = False

    def read_then_remove(source, max_bytes):
        nonlocal removed
        payload = original(source, max_bytes)
        if not removed:
            removed = True
            parent.rename(displaced)
        return payload

    monkeypatch.setattr(file_utils, "_read_bounded", read_then_remove)

    assert friday_postflight.status(
        path,
        now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc),
    ) == {"status": "invalid", "reason": "receipt-invalid"}


def test_invalid_postflight_status_rejects_undocumented_reason():
    with pytest.raises(ValueError, match="unknown postflight invalid reason"):
        friday_postflight.invalid_status("invented")
