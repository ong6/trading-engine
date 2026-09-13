"""Tests for shared strict operational-evidence validators."""

from datetime import date, datetime, timedelta, timezone

import pytest

from server.status_validation import iso_date, iso_timestamp, metadata_timestamp


def test_iso_date_accepts_only_canonical_calendar_date():
    assert iso_date("2026-09-09") == date(2026, 9, 9)


@pytest.mark.parametrize(
    "value",
    ["20260909", "2026-W37-3", "2026-9-9", "2026-09-09T00:00:00", None],
)
def test_iso_date_rejects_noncanonical_or_non_string_values(value):
    with pytest.raises(ValueError, match="must be YYYY-MM-DD"):
        iso_date(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-09T12:34:56Z", datetime(2026, 9, 9, 12, 34, 56, tzinfo=timezone.utc)),
        (
            "2026-09-09T14:34:56.123456+02:00",
            datetime(2026, 9, 9, 14, 34, 56, 123456, tzinfo=timezone(timedelta(hours=2))),
        ),
    ],
)
def test_iso_timestamp_accepts_canonical_aware_values(value, expected):
    assert iso_timestamp(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "20260909T123456+00:00",
        "2026-W37-3T12:34:56+00:00",
        "2026-09-09 12:34:56+00:00",
        "2026-09-09T12:34:56",
        "2026-09-09T12:34:56.1+00:00",
        None,
    ],
)
def test_iso_timestamp_rejects_noncanonical_naive_or_non_string_values(value):
    with pytest.raises(ValueError, match="canonical ISO 8601"):
        iso_timestamp(value)


def test_metadata_timestamp_requires_canonical_string_and_normalizes_to_utc():
    assert metadata_timestamp({"last_run": "2026-09-09T14:34:56+02:00"}) == datetime(
        2026, 9, 9, 12, 34, 56, tzinfo=timezone.utc
    )
    with pytest.raises(ValueError, match="canonical ISO timestamp"):
        metadata_timestamp({"last_run": "20260909T123456+00:00"})
