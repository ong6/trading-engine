"""Tests for liquidity evidence monitoring."""

from datetime import date, datetime, timezone

import pytest

from server import (
    liquidity_monitor,
    read_model_utils,
)


def _liquidity_meta(**overrides):
    payload = {
        "last_run": "2026-09-13T03:00:00+00:00",
        "as_of": "2026-09-11",
        "admitted": ["ADMIT"],
        "demoted": ["DEMOTE"],
        "kept_held": ["HELD"],
        "liquid_before": 2,
        "liquid_after": 2,
        "dry_run": False,
        "candidates_pulled": 3,
        "candidates_failed": 0,
        "rule": "last_close >= 3 AND median(close*volume) >= 5e6",
        "backfill": {"processed": 1, "failed": 0},
    }
    payload.update(overrides)
    return {"liquid_refresh": payload}


def _liquidity_driver(status="ok", **overrides):
    result = {
        "name": "run_weekly_liquid",
        "started_at": "2026-09-13T02:00:01Z",
        "finished_at": "2026-09-13T03:00:01Z",
        "status": status,
    }
    result.update(overrides)
    return result


def _setup_liquid_universe(con):
    con.execute("CREATE TABLE universe (ticker VARCHAR, liquid BOOLEAN)")
    con.executemany(
        "INSERT INTO universe VALUES (?, ?)",
        [("ADMIT", True), ("HELD", True), ("OTHER", False)],
    )


@pytest.mark.parametrize(
    "result",
    [
        {"status": "invented"},
        {"status": "invalid", "reason": "invented"},
    ],
)
def test_liquidity_public_status_rejects_undocumented_vocabulary(result):
    with pytest.raises(ValueError, match="undocumented liquidity"):
        liquidity_monitor._public_status(result)


def test_liquidity_evidence_is_neutral_before_first_scheduled_run(con):
    assert liquidity_monitor.evidence_status({}, None, con, None) == {
        "status": "not-yet-run",
        "reason": "no-scheduled-run",
    }


def test_liquidity_evidence_tracks_running_driver_without_requiring_artifact(con):
    assert liquidity_monitor.evidence_status(
        {}, _liquidity_driver("running", finished_at=None), con, None
    ) == {"status": "updating"}


def test_liquidity_evidence_requires_current_coherent_artifact(con):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(),
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result == {
        "status": "current",
        "reason": None,
        "as_of": date(2026, 9, 11),
        "published_at": "2026-09-13T03:00:00+00:00",
        "admitted": 1,
        "demoted": 1,
        "kept_held": 1,
        "liquid_before": 2,
        "liquid_after": 2,
        "candidates_pulled": 3,
        "candidates_failed": 0,
        "backfill_processed": 1,
        "backfill_failed": 0,
    }


def test_liquidity_evidence_reports_zero_backfill_when_no_names_are_admitted(con):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(
            admitted=[],
            demoted=[],
            liquid_before=2,
            liquid_after=2,
            backfill={"processed": 0, "failed": 0},
        ),
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result["status"] == "current"
    assert result["backfill_processed"] == 0
    assert result["backfill_failed"] == 0


def test_liquidity_evidence_requires_backfill_accounting_without_admissions(con):
    _setup_liquid_universe(con)
    meta = _liquidity_meta(
        admitted=[],
        demoted=[],
        liquid_before=2,
        liquid_after=2,
    )
    del meta["liquid_refresh"]["backfill"]

    result = liquidity_monitor.evidence_status(
        meta,
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}


def test_liquidity_evidence_remains_current_after_later_nightly_data(con):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(),
        _liquidity_driver(),
        con,
        date(2026, 9, 14),
        now=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )

    assert result["status"] == "current"


def test_liquidity_evidence_allows_subsecond_publication_within_finish_marker(con):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(last_run="2026-09-13T03:00:01.999999+00:00"),
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result["status"] == "current"


def test_liquidity_evidence_reports_store_count_mismatch(con):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(liquid_before=3, liquid_after=3),
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result == {
        "status": "stale",
        "reason": "store-count-mismatch",
        "published_at": "2026-09-13T03:00:00+00:00",
        "liquid_after": 3,
        "store_liquid": 2,
    }


@pytest.mark.parametrize(
    ("as_of", "latest", "status"),
    [
        ("2026-09-10", date(2026, 9, 11), "stale"),
        ("2026-09-12", date(2026, 9, 12), "invalid"),
    ],
)
def test_liquidity_evidence_rejects_wrong_scheduled_market_date(
    con, as_of, latest, status
):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(as_of=as_of),
        _liquidity_driver(),
        con,
        latest,
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result == {
        "status": status,
        "reason": "scheduled-market-date-mismatch",
        "as_of": date.fromisoformat(as_of),
        "expected_as_of": date(2026, 9, 11),
        "latest_date": latest,
    }


def test_liquidity_evidence_reports_unavailable_or_behind_market_store(con):
    _setup_liquid_universe(con)

    unknown = liquidity_monitor.evidence_status(
        _liquidity_meta(),
        _liquidity_driver(),
        con,
        None,
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )
    behind = liquidity_monitor.evidence_status(
        _liquidity_meta(),
        _liquidity_driver(),
        con,
        date(2026, 9, 10),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert unknown == {"status": "unknown", "reason": "market-date-unavailable"}
    assert behind == {
        "status": "invalid",
        "reason": "evidence-ahead-of-store",
        "as_of": date(2026, 9, 11),
        "latest_date": date(2026, 9, 10),
    }


@pytest.mark.parametrize(
    "status", ["failed", "interrupted", "invalid", "overdue", "stale-running"]
)
def test_liquidity_evidence_preserves_unsuccessful_driver_state(con, status):
    assert liquidity_monitor.evidence_status(
        {}, _liquidity_driver(status), con, None
    ) == {"status": status, "reason": "driver-not-successful"}


@pytest.mark.parametrize(
    ("meta", "driver", "expected_status", "expected_reason"),
    [
        ({}, _liquidity_driver(), "missing", "evidence-missing"),
        (
            _liquidity_meta(last_run="2026-09-13T01:59:59+00:00"),
            _liquidity_driver(),
            "stale",
            "evidence-predates-latest-run",
        ),
        (
            _liquidity_meta(last_run="2026-09-13T03:00:02+00:00"),
            _liquidity_driver(),
            "invalid",
            "evidence-postdates-latest-run",
        ),
        (
            _liquidity_meta(last_run="2026-09-13T05:00:00+00:00"),
            _liquidity_driver(),
            "invalid",
            "future-evidence",
        ),
        (
            _liquidity_meta(liquid_after=3),
            _liquidity_driver(),
            "invalid",
            "malformed-evidence",
        ),
        (
            _liquidity_meta(as_of="2026-W37-5"),
            _liquidity_driver(),
            "invalid",
            "malformed-evidence",
        ),
        (
            _liquidity_meta(last_run="20260913T030000+00:00"),
            _liquidity_driver(),
            "invalid",
            "malformed-evidence",
        ),
        (
            _liquidity_meta(),
            _liquidity_driver(started_at="20260913T020001Z"),
            "invalid",
            "malformed-evidence",
        ),
        (
            _liquidity_meta(),
            _liquidity_driver(finished_at="20260913T030001Z"),
            "invalid",
            "malformed-evidence",
        ),
        (
            _liquidity_meta(),
            _liquidity_driver(finished_at="2026-09-13T01:00:01Z"),
            "invalid",
            "malformed-evidence",
        ),
        (
            _liquidity_meta(candidates_failed=1),
            _liquidity_driver(),
            "issues",
            "candidate-download-failures",
        ),
        (
            _liquidity_meta(backfill={"processed": 1, "failed": 1}),
            _liquidity_driver(),
            "issues",
            "backfill-failures",
        ),
        (
            _liquidity_meta(
                admitted=[],
                demoted=[],
                liquid_before=2,
                liquid_after=2,
                backfill={"processed": 1, "failed": 1},
            ),
            _liquidity_driver(),
            "issues",
            "backfill-failures",
        ),
        (
            _liquidity_meta(
                candidates_failed=1,
                backfill={"processed": 1, "failed": 1},
            ),
            _liquidity_driver(),
            "issues",
            "candidate-and-backfill-failures",
        ),
        (
            _liquidity_meta(),
            _liquidity_driver("failed"),
            "failed",
            "driver-not-successful",
        ),
    ],
)
def test_liquidity_evidence_fails_closed(con, meta, driver, expected_status, expected_reason):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        meta,
        driver,
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result["status"] == expected_status
    assert result["reason"] == expected_reason
    if expected_reason == "malformed-evidence":
        assert "detail" not in result


def test_liquidity_evidence_rejects_unsafe_published_count(con):
    _setup_liquid_universe(con)
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(liquid_before=unsafe, liquid_after=unsafe),
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}


@pytest.mark.parametrize(
    "backfill",
    [
        {"processed": 1, "failed": 2},
        {"processed": read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1, "failed": 0},
    ],
)
def test_liquidity_evidence_rejects_incoherent_backfill_counts(con, backfill):
    _setup_liquid_universe(con)

    result = liquidity_monitor.evidence_status(
        _liquidity_meta(backfill=backfill),
        _liquidity_driver(),
        con,
        date(2026, 9, 11),
        now=datetime(2026, 9, 13, 4, tzinfo=timezone.utc),
    )

    assert result == {"status": "invalid", "reason": "malformed-evidence"}
