"""Tests for loading the operational metadata snapshot."""

import json
import sys

import pytest

from server import meta_snapshot
from server.json_utils import MAX_JSON_FILE_BYTES, load_object


def test_full_universe_metadata_retains_complete_verifier_summary(tmp_path):
    results = [{
        "ticker": f"T{index}", "sessions_compared": 5, "bars_compared": 5,
        "fields_compared": 17, "disagreements": [], "store_missing": [],
        "status": "agrees", "why": "liquid",
        "worst": {"ticker": f"T{index}", "date": "2026-10-02", "field": "low",
                  "store": 100.001, "source": 100.0, "diff_bp": 0.1},
    } for index in range(4054)]
    payload = {"regime": "risk-on", "price_verify": {"name_results": results},
               "last_run": "2026-10-02T22:32:47+00:00"}
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(payload, indent=2))
    assert MAX_JSON_FILE_BYTES < path.stat().st_size < meta_snapshot.MAX_META_SNAPSHOT_BYTES
    assert meta_snapshot.load(path) == (payload, {"status": "ok", "path": str(path)})
    # The larger aggregate allowance must not change other operational readers.
    with pytest.raises(ValueError, match="exceeds"):
        load_object(path)


def test_metadata_retains_a_hard_size_ceiling(tmp_path):
    path = tmp_path / "meta.json"
    path.write_text('{"extra":"' + "x" * meta_snapshot.MAX_META_SNAPSHOT_BYTES + '"}')
    assert meta_snapshot.load(path) == (
        {}, {"status": "invalid", "reason": "malformed", "path": str(path)}
    )


@pytest.mark.parametrize("fragment", ['{"same":1,"same":2}', "NaN", "Infinity", "1e999"])
def test_large_metadata_still_rejects_ambiguous_or_nonfinite_json(tmp_path, fragment):
    path = tmp_path / "meta.json"
    path.write_text('{"padding":"' + "x" * MAX_JSON_FILE_BYTES + '","nested":' + fragment + '}')
    assert meta_snapshot.load(path)[1]["status"] == "invalid"


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
