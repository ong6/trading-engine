"""Tests for nightly evidence monitoring."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from server import nightly_monitor, p15_scoring_runner, p15_scoring_store
from sim import league
from sim.p15_books import BOOK_IDS
from tests.nightly_test_helpers import nightly_fixture

SESSION = date(2026, 9, 4)
PRIOR_SESSION = date(2026, 9, 3)
BEFORE_SCORING = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
DURING_SCORING = datetime(2026, 9, 5, 2, 40, tzinfo=timezone.utc)
AFTER_DEADLINE = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def test_nightly_evidence_reconciles_core_database_and_reports(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)

    result = nightly_monitor.evidence_status(meta, driver, con, date(2026, 9, 4), data_dir=tmp_path)

    assert result == {
        "status": "current",
        "as_of": date(2026, 9, 4),
        "screened": 2,
        "passing": 1,
        "new_today": 1,
        "universe_policy": "all",
        "active_portfolios": 1,
        "portfolios_with_equity": 1,
    }


@pytest.mark.parametrize(
    ("mutation", "status", "reason"),
    [
        (lambda meta, driver, con, root: meta.update(screened=3), "invalid", "evidence-invalid"),
        (
            lambda meta, driver, con, root: meta.update(screen_date="20260904"),
            "invalid",
            "evidence-invalid",
        ),
        (
            lambda meta, driver, con, root: con.execute(
                "DELETE FROM sim_equity WHERE portfolio_id='paper'"
            ),
            "incomplete",
            "active-equity-missing",
        ),
    ],
)
def test_nightly_evidence_fails_closed(con, tmp_path, mutation, status, reason):
    meta, driver = nightly_fixture(con, tmp_path)
    mutation(meta, driver, con, tmp_path)

    result = nightly_monitor.evidence_status(meta, driver, con, date(2026, 9, 4), data_dir=tmp_path)

    assert result["status"] == status
    assert result["reason"] == reason
    if reason == "evidence-invalid":
        assert "detail" not in result


def _add_p15_books(con, *dates):
    for book_id in BOOK_IDS:
        con.execute(
            "INSERT INTO portfolios "
            "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
            "VALUES (?,?,'agent_only_policy','{}',DATE '2026-09-01',TRUE,100,100,'baseline_v1')",
            [book_id, book_id],
        )
        for equity_date in dates:
            con.execute("INSERT INTO sim_equity VALUES (?,?,100,100,0)", [book_id, equity_date])


def _mark_p15_session(con, session=SESSION):
    con.executemany(
        "INSERT INTO sim_equity VALUES (?,?,100,100,0)",
        [(book_id, session) for book_id in BOOK_IDS],
    )


def _record_scoring_run(con, status, session=SESSION):
    p15_scoring_store.init_schema(con)
    con.execute(
        "INSERT INTO p15_scoring_runs (id,schema_version,policy_id,market_date,"
        "universe_payload,universe_sha256,context_payload,context_sha256,status,"
        "information_cutoff_at,started_at) "
        "VALUES (1,1,?,?,'{}','u','{}','c',?,TIMESTAMP '2026-09-05 02:30:00',"
        "TIMESTAMP '2026-09-05 02:30:00')",
        [p15_scoring_store.POLICY_ID, session, status],
    )


def _render_league(con, root: Path, latest=SESSION):
    """Render the league the way the nightly and the post-scoring rerender do."""
    league.write_reports(con, latest, root)
    return (root / "reports" / "league.md").read_text()


@pytest.mark.parametrize("now", [BEFORE_SCORING, DURING_SCORING])
def test_p15_books_are_pending_until_their_scoring_run_publishes(con, tmp_path, now):
    meta, driver = nightly_fixture(con, tmp_path)
    _add_p15_books(con, PRIOR_SESSION)
    if now == DURING_SCORING:
        _record_scoring_run(con, "running")
    standings = _render_league(con, tmp_path)
    # The nightly lists each unmarked P15 book at its prior-session mark.
    assert all(f"| {book_id} |" in standings for book_id in BOOK_IDS)
    assert f"marked through {PRIOR_SESSION.isoformat()}" in standings

    result = nightly_monitor.evidence_status(
        meta, driver, con, SESSION, data_dir=tmp_path, now=now
    )

    assert result["status"] == "current"
    assert result["active_portfolios"] == 4
    assert result["portfolios_with_equity"] == 1
    assert result["portfolios_pending_publisher"] == 3
    assert result["pending_publisher"] == "p15-scoring"
    assert result["pending_due_at"] == "2026-09-05T12:00:00Z"


def test_pending_p15_books_must_still_appear_in_the_league(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)
    _add_p15_books(con, PRIOR_SESSION)

    result = nightly_monitor.evidence_status(
        meta, driver, con, SESSION, data_dir=tmp_path, now=BEFORE_SCORING
    )

    assert result == {"status": "invalid", "reason": "evidence-invalid"}


def test_p15_books_are_current_after_their_scoring_run(con, tmp_path):
    meta, driver = nightly_fixture(con, tmp_path)
    _add_p15_books(con, PRIOR_SESSION)
    _mark_p15_session(con)
    _record_scoring_run(con, "completed")
    _render_league(con, tmp_path)

    result = nightly_monitor.evidence_status(
        meta, driver, con, SESSION, data_dir=tmp_path, now=DURING_SCORING
    )

    assert result["status"] == "current"
    assert result["active_portfolios"] == 4
    assert result["portfolios_with_equity"] == 4
    assert "portfolios_pending_publisher" not in result


def _publisher_finished_without_marks(con):
    _add_p15_books(con, PRIOR_SESSION)
    _record_scoring_run(con, "completed")
    return DURING_SCORING


def _publisher_failed_without_marks(con):
    _add_p15_books(con, PRIOR_SESSION)
    _record_scoring_run(con, "failed")
    return DURING_SCORING


def _publisher_overdue(con):
    _add_p15_books(con, PRIOR_SESSION)
    return AFTER_DEADLINE


def _book_behind_more_than_one_session(con):
    _add_p15_books(con, date(2026, 9, 2))
    return BEFORE_SCORING


def _book_never_marked(con):
    _add_p15_books(con)
    return BEFORE_SCORING


def _nightly_book_missing_while_p15_pending(con):
    _add_p15_books(con, PRIOR_SESSION)
    con.execute("DELETE FROM sim_equity WHERE portfolio_id='paper' AND date=?", [SESSION])
    return BEFORE_SCORING


@pytest.mark.parametrize(
    "scenario",
    [
        _publisher_finished_without_marks,
        _publisher_failed_without_marks,
        _publisher_overdue,
        _book_behind_more_than_one_session,
        _book_never_marked,
        _nightly_book_missing_while_p15_pending,
    ],
)
def test_genuinely_missing_equity_stays_incomplete(con, tmp_path, scenario):
    meta, driver = nightly_fixture(con, tmp_path)
    now = scenario(con)
    _render_league(con, tmp_path)

    result = nightly_monitor.evidence_status(
        meta, driver, con, SESSION, data_dir=tmp_path, now=now
    )

    assert result["status"] == "incomplete"
    assert result["reason"] == "active-equity-missing"
    assert "portfolios_pending_publisher" not in result


def test_p15_publisher_identity_tracks_the_books_and_scoring_store():
    assert set(nightly_monitor.P15_BOOK_IDS) == set(BOOK_IDS)
    assert nightly_monitor.P15_POLICY_ID == p15_scoring_store.POLICY_ID


def test_p15_publish_deadline_tracks_the_scoring_runner_and_timer():
    timer = Path(nightly_monitor.__file__).with_name("trading-engine-p15-scoring.timer")

    assert p15_scoring_runner.DEADLINE_UTC.replace(tzinfo=None) == (
        nightly_monitor.P15_PUBLISH_DEADLINE_UTC
    )
    assert "OnCalendar=Tue..Sat *-*-* 02:30:00 UTC" in timer.read_text()
