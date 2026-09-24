"""Tests for market-data freshness and price-verification health."""

from datetime import date, datetime, timezone

import pytest

from server import (
    market_health,
    read_model_utils,
)


def test_market_data_freshness_uses_sessions_not_calendar_days():
    labor_day = market_health.freshness(date(2026, 9, 4), as_of=date(2026, 9, 7))
    assert labor_day == {
        "status": "ok",
        "as_of": date(2026, 9, 7),
        "latest_date": date(2026, 9, 4),
        "calendar_days": 3,
        "missing_completed_sessions": 0,
        "first_missing_session": None,
        "last_missing_session": None,
        "next_session": date(2026, 9, 8),
    }

    missed_tuesday = market_health.freshness(date(2026, 9, 4), as_of=date(2026, 9, 9))
    assert missed_tuesday["status"] == "stale"
    assert missed_tuesday["calendar_days"] == 5
    assert missed_tuesday["missing_completed_sessions"] == 1
    assert missed_tuesday["first_missing_session"] == date(2026, 9, 8)
    assert missed_tuesday["last_missing_session"] == date(2026, 9, 8)


def test_market_data_freshness_handles_missing_and_future_dates():
    unknown = market_health.freshness(None, as_of=date(2026, 9, 7))
    assert unknown["status"] == "unknown"
    assert unknown["calendar_days"] is None
    assert unknown["missing_completed_sessions"] is None

    future = market_health.freshness(date(2026, 9, 8), as_of=date(2026, 9, 7))
    assert future["status"] == "future"
    assert future["calendar_days"] == -1
    assert future["missing_completed_sessions"] == 0


def test_market_data_freshness_defaults_to_operational_utc_date(monkeypatch):
    monkeypatch.setattr(market_health, "_utc_today", lambda: date(2026, 9, 9))

    result = market_health.freshness(date(2026, 9, 4))

    assert result["as_of"] == date(2026, 9, 9)
    assert result["status"] == "stale"
    assert result["missing_completed_sessions"] == 1


def _price_verify_meta(**overrides):
    payload = {
        "last_run": "2026-09-07T22:40:00+00:00",
        "as_of": "2026-09-04",
        "names_selected": 40,
        "names_checked": 40,
        "names_agreeing": 40,
        "names_disagreeing": 0,
        "names_not_checked": 0,
        "n_disagreements": 0,
        "n_material": 0,
        "n_parse_errors": 0,
        "tolerance_bp": 10.0,
        "tolerance_abs_usd": 0.01,
        "material_bp": 200.0,
        "disagreements": [],
    }
    payload.update(overrides)
    return {"price_verify": payload}


def test_price_verification_status_accepts_current_clean_evidence():
    result = market_health.price_verification(
        _price_verify_meta(),
        date(2026, 9, 4),
        {"status": "ok", "started_at": "2026-09-07T22:30:01Z"},
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    assert result["status"] == "current"
    assert result["names_checked"] == result["names_selected"] == 40
    assert result["disagreements"] == []
    assert result["tolerance_bp"] == 10.0
    assert result["tolerance_abs_usd"] == 0.01
    assert result["material_bp"] == 200.0
    assert result["disagreements_limit"] == market_health.PRICE_DISAGREEMENT_LIMIT
    assert result["disagreements_matching_count"] == 0
    assert result["disagreements_truncated"] is False


def test_price_verification_rejects_unsafe_published_count():
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    result = market_health.price_verification(
        _price_verify_meta(names_selected=unsafe, names_checked=unsafe, names_agreeing=unsafe),
        date(2026, 9, 4),
        None,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}


def test_price_verification_publishes_bounded_worst_first_disagreements():
    detail = {
        "ticker": "VFLO",
        "date": "2026-09-04",
        "field": "close",
        "store": 55.29,
        "source": 85_780.095,
        "diff_bp": 9_993.55,
    }
    result = market_health.price_verification(
        _price_verify_meta(
            names_agreeing=39,
            names_disagreeing=1,
            n_disagreements=1,
            n_material=1,
            disagreements=[detail],
        ),
        date(2026, 9, 4),
        None,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert result["status"] == "issues"
    assert result["disagreements"] == [{**detail, "date": date(2026, 9, 4)}]
    assert result["disagreements_matching_count"] == 1
    assert result["disagreements_truncated"] is False


def test_price_verification_caps_disagreements_with_explicit_truncation():
    details = [
        {
            "ticker": f"T{index}",
            "date": "2026-09-04",
            "field": "close",
            "store": 100.0,
            "source": 101.9 - index * 0.05,
            "diff_bp": round(
                (1.9 - index * 0.05) / (101.9 - index * 0.05) * 10_000,
                2,
            ),
        }
        for index in range(market_health.PRICE_DISAGREEMENT_LIMIT)
    ]
    result = market_health.price_verification(
        _price_verify_meta(
            names_selected=40,
            names_checked=40,
            names_agreeing=20,
            names_disagreeing=20,
            n_disagreements=market_health.PRICE_DISAGREEMENT_LIMIT + 1,
            n_material=0,
            disagreements=details,
        ),
        date(2026, 9, 4),
        None,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert len(result["disagreements"]) == market_health.PRICE_DISAGREEMENT_LIMIT
    assert result["disagreements_matching_count"] == market_health.PRICE_DISAGREEMENT_LIMIT + 1
    assert result["disagreements_truncated"] is True


@pytest.mark.parametrize(
    "disagreements",
    [
        [],
        [{"ticker": "VFLO", "date": "2026-09-04", "field": "close"}],
        [
            {
                "ticker": "VFLO",
                "date": "2026-09-05",
                "field": "close",
                "store": 55.29,
                "source": 85_780.095,
                "diff_bp": 9_993.55,
            }
        ],
        [
            {
                "ticker": "VFLO",
                "date": "2026-09-04",
                "field": "volume",
                "store": 55.29,
                "source": 85_780.095,
                "diff_bp": 9_993.55,
            }
        ],
        [
            {
                "ticker": "VFLO",
                "date": "2026-09-04",
                "field": "close",
                "store": float("nan"),
                "source": 85_780.095,
                "diff_bp": 9_993.55,
            }
        ],
    ],
)
def test_price_verification_rejects_malformed_disagreement_details(disagreements):
    result = market_health.price_verification(
        _price_verify_meta(
            names_agreeing=39,
            names_disagreeing=1,
            n_disagreements=1,
            n_material=1,
            disagreements=disagreements,
        ),
        date(2026, 9, 4),
        None,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}


@pytest.mark.parametrize("reported_diff_bp", [9_993.54, 9_993.56, float("inf")])
def test_price_verification_recomputes_reported_basis_point_difference(reported_diff_bp):
    result = market_health.price_verification(
        _price_verify_meta(
            names_agreeing=39,
            names_disagreeing=1,
            n_disagreements=1,
            n_material=1,
            disagreements=[
                {
                    "ticker": "VFLO",
                    "date": "2026-09-04",
                    "field": "close",
                    "store": 55.29,
                    "source": 85_780.095,
                    "diff_bp": reported_diff_bp,
                }
            ],
        ),
        date(2026, 9, 4),
        None,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}


def test_price_verification_accepts_two_decimal_half_cent_rounding_boundary():
    item = {"diff_bp": 59.05}
    assert market_health._price_diff_bp(item, 12.7, 12.625) == 59.05


@pytest.mark.parametrize(
    "details",
    [
        [
            {
                "ticker": "VFLO",
                "date": "2026-09-04",
                "field": "close",
                "store": 55.29,
                "source": 85_780.095,
                "diff_bp": diff_bp,
            }
            for diff_bp in (9_993.55, 9_993.55)
        ],
        [
            {
                "ticker": ticker,
                "date": "2026-09-04",
                "field": "close",
                "store": 100.0,
                "source": source,
                "diff_bp": round((source - 100.0) / source * 10_000, 2),
            }
            for ticker, source in (("VFLO", 100.2), ("VTEC", 100.3))
        ],
    ],
)
def test_price_verification_rejects_duplicate_or_unsorted_disagreements(details):
    result = market_health.price_verification(
        _price_verify_meta(
            names_agreeing=38,
            names_disagreeing=2,
            n_disagreements=2,
            disagreements=details,
        ),
        date(2026, 9, 4),
        None,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}


@pytest.mark.parametrize(
    ("meta", "latest", "nightly", "status", "reason"),
    [
        ({}, date(2026, 9, 4), None, "missing", None),
        ({"price_verify": []}, date(2026, 9, 4), None, "invalid", "not-an-object"),
        (
            _price_verify_meta(names_checked=39),
            date(2026, 9, 4),
            None,
            "invalid",
            "malformed-evidence",
        ),
        (
            _price_verify_meta(as_of="20260904"),
            date(2026, 9, 4),
            None,
            "invalid",
            "malformed-evidence",
        ),
        (
            _price_verify_meta(last_run="20260907T224000+00:00"),
            date(2026, 9, 4),
            None,
            "invalid",
            "malformed-evidence",
        ),
        (
            _price_verify_meta(),
            date(2026, 9, 4),
            {"status": "ok", "started_at": "20260907T223001Z"},
            "invalid",
            "malformed-evidence",
        ),
        (
            _price_verify_meta(as_of="2026-09-03"),
            date(2026, 9, 4),
            None,
            "stale",
            "market-date-behind",
        ),
        (
            _price_verify_meta(last_run="2026-09-07T22:20:00+00:00"),
            date(2026, 9, 4),
            {"status": "ok", "started_at": "2026-09-07T22:30:01Z"},
            "stale",
            "not-refreshed-by-latest-nightly",
        ),
        (
            _price_verify_meta(
                names_selected=1,
                names_checked=0,
                names_agreeing=0,
                names_not_checked=1,
            ),
            date(2026, 9, 4),
            None,
            "incomplete",
            "no-names-checked",
        ),
        (
            _price_verify_meta(
                names_selected=40,
                names_checked=39,
                names_agreeing=39,
                names_not_checked=1,
            ),
            date(2026, 9, 4),
            None,
            "partial",
            "selected-names-not-checked",
        ),
        (
            _price_verify_meta(
                names_agreeing=39,
                names_disagreeing=1,
                n_disagreements=2,
                n_material=2,
                disagreements=[
                    {
                        "ticker": "VFLO",
                        "date": "2026-09-04",
                        "field": field,
                        "store": 55.29,
                        "source": 85_780.095,
                        "diff_bp": 9_993.55,
                    }
                    for field in ("close", "open")
                ],
            ),
            date(2026, 9, 4),
            None,
            "issues",
            "disagreements-or-parse-errors",
        ),
        (
            _price_verify_meta(n_parse_errors=1),
            date(2026, 9, 4),
            None,
            "issues",
            "disagreements-or-parse-errors",
        ),
    ],
)
def test_price_verification_status_fails_closed(meta, latest, nightly, status, reason):
    result = market_health.price_verification(
        meta,
        latest,
        nightly,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    assert result["status"] == status
    if reason is not None:
        assert result["reason"] == reason
    if reason == "malformed-evidence":
        assert "detail" not in result
