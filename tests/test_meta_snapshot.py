"""Tests for loading the operational metadata snapshot."""

import sys

import pytest

from server import meta_snapshot


def test_meta_snapshot_status_is_explicit(tmp_path):
    missing = tmp_path / "missing.json"
    assert meta_snapshot.load(missing) == (
        {},
        {"status": "missing", "path": str(missing)},
    )

    malformed = tmp_path / "malformed.json"
    malformed.write_text("not json")
    payload, status = meta_snapshot.load(malformed)
    assert payload == {}
    assert status == {
        "status": "invalid",
        "reason": "unreadable-or-malformed",
        "path": str(malformed),
    }

    wrong_shape = tmp_path / "array.json"
    wrong_shape.write_text("[]")
    assert meta_snapshot.load(wrong_shape)[1]["reason"] == "malformed"

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"last_run": "first", "last_run": "second"}')
    assert meta_snapshot.load(duplicate)[1]["reason"] == "malformed"

    valid = tmp_path / "valid.json"
    valid.write_text('{"last_run": "2026-09-04"}')
    assert meta_snapshot.load(valid) == (
        {"last_run": "2026-09-04"},
        {"status": "ok", "path": str(valid)},
    )


def test_excessively_nested_snapshot_is_reported_as_invalid(tmp_path):
    path = tmp_path / "meta.json"
    depth = max(10_000, sys.getrecursionlimit() * 10)
    path.write_text('{"nested":' + ("[" * depth) + "0" + ("]" * depth) + "}")

    payload, status = meta_snapshot.load(path)

    assert payload == {}
    assert status == {
        "status": "invalid",
        "reason": "malformed",
        "path": str(path),
    }


def test_symlinked_snapshot_is_reported_as_invalid(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"last_run": "2026-09-04"}')
    path = tmp_path / "meta.json"
    path.symlink_to(target)

    payload, status = meta_snapshot.load(path)

    assert payload == {}
    assert status == {
        "status": "invalid",
        "reason": "not-regular",
        "path": str(path),
    }


def test_dangling_symlinked_snapshot_is_invalid_not_missing(tmp_path):
    path = tmp_path / "meta.json"
    path.symlink_to(tmp_path / "missing-target.json")

    assert meta_snapshot.load(path)[1] == {
        "status": "invalid",
        "reason": "not-regular",
        "path": str(path),
    }


def test_nonregular_snapshot_is_reported_as_invalid(tmp_path):
    path = tmp_path / "meta.json"
    path.mkdir()

    assert meta_snapshot.load(path)[1] == {
        "status": "invalid",
        "reason": "not-regular",
        "path": str(path),
    }


def test_public_summary_exposes_only_validated_header_fields():
    payload = {
        "regime": "risk-on",
        "last_run": "2026-09-12T12:00:00+00:00",
        "last_screen": None,
        "screen_date": "2026-09-11",
        "price_verify": {"disagreements": ["private producer detail"]},
        "stale_tickers": {"list": ["PRIVATE"]},
    }

    assert meta_snapshot.public_summary(payload) == {
        "regime": "risk-on",
        "last_run": "2026-09-12T12:00:00+00:00",
        "last_screen": None,
        "screen_date": "2026-09-11",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"regime": "maybe"},
        {"regime": None},
        {"last_run": "2026-09-12T12:00:00"},
        {"last_screen": "20260912T120000Z"},
        {"screen_date": "2026-02-30"},
    ],
)
def test_public_summary_rejects_malformed_present_fields(payload):
    with pytest.raises(ValueError):
        meta_snapshot.public_summary(payload)
