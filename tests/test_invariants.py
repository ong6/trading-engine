"""Snapshot invariants: a good and a bad fixture per invariant, and pinned shared constants."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta

import duckdb
import pytest

from tools import invariants
from tools.invariants import books, market_data, registry

AS_OF = datetime(2026, 10, 20, 3, 55, tzinfo=UTC)
DAY_ZERO = date(2026, 10, 19)
FRIDAY = date(2026, 10, 16)
P15 = books.P15_BOOK_IDS

DDL = """
CREATE TABLE prices (ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
    close DOUBLE, volume BIGINT, fetched_at TIMESTAMP, PRIMARY KEY (ticker, date));
CREATE TABLE universe (ticker VARCHAR, liquid BOOLEAN);
CREATE TABLE corporate_actions (ticker VARCHAR, ex_date DATE, kind VARCHAR, value DOUBLE);
CREATE TABLE split_adjustments (ticker VARCHAR, ex_date DATE, outcome VARCHAR);
CREATE TABLE portfolios (id VARCHAR, created DATE, active BOOLEAN, initial_cash DOUBLE);
CREATE TABLE portfolio_accounts (portfolio_id VARCHAR, cost_profile VARCHAR);
CREATE TABLE sim_book_breaks (portfolio_id VARCHAR, break_date DATE, kind VARCHAR,
    to_value VARCHAR);
CREATE TABLE sim_fills (order_id BIGINT, portfolio_id VARCHAR, ticker VARCHAR, side VARCHAR,
    qty DOUBLE, fill_date DATE);
CREATE TABLE sim_fill_fees (order_id BIGINT, cost_profile VARCHAR, total_usd DOUBLE);
CREATE TABLE sim_equity (portfolio_id VARCHAR, date DATE, equity DOUBLE, cash DOUBLE);
CREATE TABLE sim_positions (portfolio_id VARCHAR, ticker VARCHAR, qty DOUBLE);
CREATE TABLE sim_settlements (portfolio_id VARCHAR, ticker VARCHAR, kind VARCHAR,
    effective DATE, price DOUBLE, qty DOUBLE, created_at TIMESTAMP);
CREATE TABLE p15_scoring_runs (id BIGINT, market_date DATE, status VARCHAR,
    started_at TIMESTAMP, completed_at TIMESTAMP);
CREATE TABLE p15_book_windows (portfolio_id VARCHAR, market_date DATE, equity DOUBLE,
    completed_at TIMESTAMP);
CREATE TABLE p15_preopen_runs (id BIGINT, session_date DATE, status VARCHAR, reason VARCHAR,
    started_at TIMESTAMP, completed_at TIMESTAMP);
CREATE TABLE p15_order_intents (id BIGINT, order_role VARCHAR);
CREATE TABLE p15_book_fills (intent_id BIGINT, portfolio_id VARCHAR, fill_date DATE);
CREATE TABLE experiment_results (experiment_id VARCHAR, config_hash VARCHAR,
    partition VARCHAR, trade_date DATE, mean_ret DOUBLE, sharpe_annual DOUBLE,
    n_trades INTEGER, meta_json VARCHAR);
"""


def _sessions(end: date, count: int) -> list[date]:
    days, day = [], end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days[::-1]


SESSIONS = _sessions(DAY_ZERO, 80)


def _same_night(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=22, minutes=30)


def _settled(day: date) -> datetime:
    """The next night's re-fetch (22:30 UTC is 18:30 in New York)."""
    return _same_night(day + timedelta(days=1))


def _bars(con, ticker: str, closes: list[float], volumes: list[float] | None = None,
          days: list[date] = SESSIONS) -> None:
    volumes = volumes or [1_000_000] * len(closes)
    con.executemany("INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (ticker, day, close, close * 1.01, close * 0.99, close, volume,
         _same_night(day) if day == days[-1] else _settled(day))
        for day, close, volume in zip(days, closes, volumes, strict=True)])


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute(DDL)
    _bars(connection, "AAA", [100.0] * len(SESSIONS))
    _bars(connection, "BBB", [50.0] * len(SESSIONS))
    connection.execute("INSERT INTO universe VALUES ('AAA', true), ('BBB', true)")
    # A recorded 2:1 split whose stored series is already continuous (restated).
    connection.execute("INSERT INTO corporate_actions VALUES ('AAA', ?, 'split', 2.0)",
                       [SESSIONS[-30]])
    connection.execute("INSERT INTO split_adjustments VALUES ('AAA', ?, 'applied')",
                       [SESSIONS[-30]])
    connection.executemany("INSERT INTO portfolios VALUES (?, ?, ?, 10000.0)", [
        ("alpha", date(2026, 1, 2), True), ("retired", date(2026, 1, 2), False),
        *((book, date(2026, 9, 26), True) for book in P15)])
    for book in ("alpha", *P15):
        connection.execute("INSERT INTO portfolio_accounts VALUES (?, ?)",
                           [book, books.FEE_PROFILE])
        connection.execute("INSERT INTO sim_book_breaks VALUES (?, ?, 'cost_profile', ?)",
                           [book, DAY_ZERO, books.FEE_PROFILE])
    connection.executemany("INSERT INTO sim_fills VALUES (?, ?, ?, ?, 1.0, ?)", [
        (1, "alpha", "AAA", "buy", FRIDAY), (2, "alpha", "BBB", "buy", DAY_ZERO),
        (3, "alpha", "CCC", "buy", date(2026, 10, 1)), (4, "p15_ai_ranked", "AAA", "buy",
                                                         DAY_ZERO)])
    connection.executemany("INSERT INTO sim_fill_fees VALUES (?, ?, ?)", [
        (2, books.FEE_PROFILE, 0.35), (4, books.FEE_PROFILE, 0.35)])
    connection.execute("INSERT INTO sim_positions VALUES ('alpha', 'BBB', 1.0), "
                       "('alpha', 'CCC', 0.0)")
    connection.execute("INSERT INTO sim_settlements VALUES ('alpha', 'CCC', 'cash', "
                       "'2026-10-05', 30.94, 1.0, '2026-10-19 22:37:00')")
    connection.executemany("INSERT INTO sim_equity VALUES (?, ?, ?, ?)", [
        ("alpha", FRIDAY, 10010.0, 100.0), ("alpha", DAY_ZERO, 10020.0, 100.0),
        ("retired", date(2026, 8, 17), 9000.0, 9000.0),
        *((book, date(2026, 9, 28), 10000.0, 10000.0) for book in P15),
        *((book, day, 9900.0 + index, 500.0) for book in P15
          for index, day in enumerate((FRIDAY, DAY_ZERO)))])
    for index, day in enumerate((FRIDAY, DAY_ZERO)):
        started = _same_night(day + timedelta(days=1)) - timedelta(hours=20)
        connection.execute("INSERT INTO p15_scoring_runs VALUES (?, ?, 'completed', ?, ?)",
                           [index + 1, day, started, started + timedelta(minutes=16)])
        connection.executemany("INSERT INTO p15_book_windows VALUES (?, ?, ?, ?)", [
            (book, day, 9900.0 + index, started + timedelta(minutes=16, seconds=30))
            for book in P15])
        opened = datetime.combine(day, datetime.min.time()) + timedelta(hours=13, minutes=5)
        connection.execute("INSERT INTO p15_preopen_runs VALUES (?, ?, 'completed', NULL, ?, ?)",
                           [index + 1, day, opened, opened + timedelta(seconds=20)])
    connection.execute("INSERT INTO p15_order_intents VALUES (1, 'entry'), (2, 'stop')")
    connection.execute("INSERT INTO p15_book_fills VALUES (1, 'p15_ai_ranked', ?), "
                       "(2, 'p15_ai_ranked', '2026-10-14')", [DAY_ZERO])
    connection.execute("INSERT INTO experiment_results VALUES ('exp', 'abcdef0123456789', "
                       "'validate', '2026-10-01', 0.01, 1.2, 10, '{\"t\": 1.5}')")
    yield connection
    connection.close()


@pytest.fixture
def engine_root(tmp_path):
    results = tmp_path / "data" / "reports" / "walkforward" / "results"
    results.mkdir(parents=True)
    (results / "alpha.json").write_text(json.dumps({"folds": [{"train": {"sharpe": 1.0}}]}))
    experiments = tmp_path / "data" / "reports" / "experiments" / "exp"
    experiments.mkdir(parents=True)
    (experiments / "result.json").write_text(json.dumps({"t": 2.0}))
    return tmp_path


def _check(con, engine_root, name: str, as_of: datetime = AS_OF) -> tuple[dict, list[dict]]:
    ctx = registry.Context(con=con, snapshot_as_of=as_of, engine_root=engine_root)
    return invariants.INVARIANTS[name].check(ctx)


def _classes(found: list[dict]) -> set[tuple[str, str]]:
    return {(item["class"], item["subject"]) for item in found}


def test_every_invariant_passes_the_good_fixture(con, engine_root):
    ctx = registry.Context(con=con, snapshot_as_of=AS_OF, engine_root=engine_root)
    result = registry.evaluate(ctx, [], today=AS_OF.date())
    assert {name: item["status"] for name, item in result["invariants"].items()} == dict.fromkeys(
        registry.ordered_names(), "pass")
    assert result["status"] == "pass"
    assert list(result["invariants"])[:3] == [
        "ohlc_geometry", "one_split_basis_per_ticker", "split_recorded_vs_restated"]


def test_ohlc_geometry_classes_provisional_stale_and_settled_bars(con, engine_root):
    latest, older = SESSIONS[-1], SESSIONS[-6]
    con.execute("UPDATE prices SET open = high * 1.02 WHERE ticker = 'AAA' AND date = ?",
                [latest])
    con.execute("UPDATE prices SET open = high * 1.02, fetched_at = ? WHERE ticker = 'BBB' "
                "AND date = ?", [_same_night(older), older])
    con.execute("UPDATE prices SET close = low * 0.5 WHERE ticker = 'BBB' AND date = ?",
                [SESSIONS[-20]])
    con.execute("UPDATE prices SET open = 0 WHERE ticker = 'AAA' AND date = ?", [SESSIONS[-30]])

    facts, found = _check(con, engine_root, "ohlc_geometry")

    assert _classes(found) == {
        ("provisional", f"AAA {latest}"), ("stale_provisional", f"BBB {older}"),
        ("settled", f"BBB {SESSIONS[-20]}"), ("settled", f"AAA {SESSIONS[-30]}")}
    shapes = {item["subject"]: item["detail"]["shape"] for item in found}
    assert shapes[f"AAA {SESSIONS[-30]}"] == "nonpositive"
    assert shapes[f"BBB {SESSIONS[-20]}"] == "close_outside_range"
    assert facts["latest_session_impossible"] == 1
    assert facts["latest_session_impossible_pct"] == 50.0


def test_one_split_basis_flags_a_recorded_split_left_unrestated(con, engine_root):
    ex = SESSIONS[-20]
    con.execute("INSERT INTO corporate_actions VALUES ('BBB', ?, 'split', 2.0)", [ex])
    con.execute("INSERT INTO split_adjustments VALUES ('BBB', ?, 'skipped_already_adjusted')",
                [ex])
    assert _check(con, engine_root, "one_split_basis_per_ticker")[1] == []

    con.execute("UPDATE prices SET close = 100.0 WHERE ticker = 'BBB' AND date < ?",
                [SESSIONS[-22]])
    facts, found = _check(con, engine_root, "one_split_basis_per_ticker")

    assert _classes(found) == {("skipped_already_adjusted", f"BBB {ex}")}
    assert found[0]["detail"]["sessions_from_ex"] == -2
    assert facts == {"liquid_splits_checked": 2, "mixed_basis": 1}


def _reverse_split(con, ticker: str, at: int) -> None:
    """A 1:5 reverse split at SESSIONS[at]: price x5, volume /5, nothing recorded."""
    closes = [10.0 if index < len(SESSIONS) + at else 50.0 for index in range(len(SESSIONS))]
    volumes = [5_000_000 if index < len(SESSIONS) + at else 1_000_000
               for index in range(len(SESSIONS))]
    _bars(con, ticker, closes, volumes)
    con.execute("INSERT INTO universe VALUES (?, true)", [ticker])


def test_split_recorded_vs_restated_flags_an_unrecorded_split_sized_break(con, engine_root):
    _reverse_split(con, "CCC", -10)
    facts, found = _check(con, engine_root, "split_recorded_vs_restated")
    assert _classes(found) == {("unrecorded", f"CCC {SESSIONS[-10]}")}
    assert found[0]["detail"]["ratio"] == pytest.approx(0.2)
    assert facts["unrecorded"] == 1

    con.execute("INSERT INTO corporate_actions VALUES ('CCC', ?, 'split', 0.2)",
                [SESSIONS[-10] + timedelta(days=3)])
    assert _check(con, engine_root, "split_recorded_vs_restated")[1] == []


def test_split_scan_ignores_glitches_old_breaks_and_moves_without_volume_shift(
        con, engine_root):
    _reverse_split(con, "OLD", -70)            # before the scan window
    closes = [20.0] * len(SESSIONS)
    closes[-5] = 10.0                          # single-bar glitch, reversed next bar
    _bars(con, "GLI", closes)
    closes = [20.0] * (len(SESSIONS) - 8) + [10.0] * 8   # halving, volume unchanged
    _bars(con, "CRS", closes)
    con.execute("INSERT INTO universe VALUES ('OLD', true), ('GLI', true), ('CRS', true)")
    assert _check(con, engine_root, "split_recorded_vs_restated")[1] == []


def test_fee_row_per_fill_from_day_zero(con, engine_root):
    facts, found = _check(con, engine_root, "fee_row_per_fill")
    assert found == []
    assert facts["by_fill_date"] == {"2026-10-19": {"fills": 2, "with_fee_row": 2,
                                                    "fees_usd": 0.7}}

    con.execute("INSERT INTO sim_fills VALUES (5, 'alpha', 'AAA', 'sell', 1.0, ?), "
                "(6, 'alpha', 'BBB', 'sell', 1.0, ?), (7, 'alpha', 'AAA', 'buy', 1.0, ?)",
                [DAY_ZERO] * 3)
    con.execute("INSERT INTO sim_fill_fees VALUES (6, ?, 0.1), (6, ?, 0.1), "
                "(7, 'baseline_v1', 0.0), (2, ?, 'nan')", [books.FEE_PROFILE] * 3)
    con.execute("DELETE FROM sim_fill_fees WHERE order_id = 2 AND total_usd = 0.35")
    _facts, found = _check(con, engine_root, "fee_row_per_fill")
    assert _classes(found) == {("missing", "order 5"), ("duplicate", "order 6"),
                               ("wrong_profile", "order 7"), ("nonfinite", "order 2")}


def test_equity_per_active_book_after_each_publisher(con, engine_root):
    facts, found = _check(con, engine_root, "equity_per_active_book")
    assert found == []
    assert (facts["active_books"], facts["books_with_equity"]) == (4, 4)

    # Before the P15 scoring run for the session: P15 books are pending, not missing.
    con.execute("DELETE FROM sim_equity WHERE portfolio_id LIKE 'p15_%' AND date = ?",
                [DAY_ZERO])
    con.execute("DELETE FROM p15_scoring_runs WHERE market_date = ?", [DAY_ZERO])
    early = datetime(2026, 10, 19, 23, 53, tzinfo=UTC)
    facts, found = _check(con, engine_root, "equity_per_active_book", early)
    assert found == []
    assert facts["pending_publisher"] == sorted(P15)
    assert facts["p15_session"] == FRIDAY.isoformat()

    # After the scoring deadline the same gap is an overdue publisher and missing marks.
    late = datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
    _facts, found = _check(con, engine_root, "equity_per_active_book", late)
    assert _classes(found) == {("publisher_overdue", "p15 scoring"),
                               *(("missing", book) for book in P15)}


def test_equity_flags_a_missing_league_mark_and_a_league_behind_prices(con, engine_root):
    con.execute("INSERT INTO portfolios VALUES ('beta', '2026-01-02', true, 10000.0)")
    con.execute("INSERT INTO sim_equity VALUES ('beta', ?, 10000.0, 10000.0)", [DAY_ZERO])
    con.execute("DELETE FROM sim_equity WHERE portfolio_id = 'alpha' AND date = ?", [DAY_ZERO])
    _facts, found = _check(con, engine_root, "equity_per_active_book")
    assert _classes(found) == {("missing", "alpha")}

    con.execute("DELETE FROM sim_equity WHERE portfolio_id = 'beta'")
    _facts, found = _check(con, engine_root, "equity_per_active_book")
    assert ("behind_prices", "league") in _classes(found)


def test_equity_flags_a_nonfinite_mark(con, engine_root):
    con.execute("UPDATE sim_equity SET equity = 'nan' WHERE portfolio_id = 'alpha' "
                "AND date = ?", [DAY_ZERO])
    _facts, found = _check(con, engine_root, "equity_per_active_book")
    assert _classes(found) == {("nonfinite", "alpha")}


def test_closeouts_once(con, engine_root):
    facts, found = _check(con, engine_root, "closeouts_once")
    assert found == []
    assert facts["recent"] == [{"portfolio_id": "alpha", "ticker": "CCC",
                                "effective": "2026-10-05", "price": 30.94}]

    con.execute("INSERT INTO sim_settlements VALUES ('alpha', 'CCC', 'cash', '2026-10-07', "
                "30.94, 1.0, '2026-10-19 22:38:00')")
    con.execute("UPDATE sim_positions SET qty = 1.0 WHERE ticker = 'CCC'")
    con.execute("INSERT INTO sim_fills VALUES (8, 'alpha', 'CCC', 'sell', 1.0, '2026-10-09')")
    _facts, found = _check(con, engine_root, "closeouts_once")
    assert _classes(found) == {("repeated", "alpha CCC"), ("position_survives", "alpha CCC"),
                               ("sold_after_closeout", "alpha CCC")}


def test_closeout_after_a_rebuy_is_not_repeated(con, engine_root):
    con.execute("INSERT INTO sim_fills VALUES (9, 'alpha', 'CCC', 'buy', 1.0, '2026-10-12')")
    con.execute("INSERT INTO sim_settlements VALUES ('alpha', 'CCC', 'cash', '2026-10-14', "
                "31.0, 1.0, '2026-10-19 22:38:00')")
    assert _check(con, engine_root, "closeouts_once")[1] == []


def test_publication_order(con, engine_root):
    assert _check(con, engine_root, "publication_order")[1] == []

    con.execute("UPDATE sim_equity SET equity = equity + 26.8 WHERE portfolio_id = "
                "'p15_rule_control' AND date = ?", [DAY_ZERO])
    con.execute("DELETE FROM p15_book_windows WHERE portfolio_id = 'p15_hybrid_veto' "
                "AND market_date = ?", [FRIDAY])
    con.execute("UPDATE p15_book_windows SET completed_at = '2026-10-19 22:36:45' "
                "WHERE portfolio_id = 'p15_ai_ranked' AND market_date = ?", [DAY_ZERO])
    con.execute("UPDATE p15_preopen_runs SET completed_at = '2026-10-16 13:31:00' "
                "WHERE session_date = ?", [FRIDAY])
    _facts, found = _check(con, engine_root, "publication_order")
    assert _classes(found) == {
        ("mark_differs_from_window", f"p15_rule_control {DAY_ZERO}"),
        ("mark_without_window", f"p15_hybrid_veto {FRIDAY}"),
        ("partial_window_set", f"windows {FRIDAY}"),
        ("window_before_scoring_run", f"p15_ai_ranked {DAY_ZERO}"),
        ("preopen_after_open", f"preopen {FRIDAY}")}


def test_publication_order_flags_scoring_before_the_close(con, engine_root):
    con.execute("UPDATE p15_scoring_runs SET started_at = '2026-10-19 19:00:00' "
                "WHERE market_date = ?", [DAY_ZERO])
    _facts, found = _check(con, engine_root, "publication_order")
    assert _classes(found) == {("scoring_before_close", f"scoring {DAY_ZERO}")}


def test_preopen_not_voided(con, engine_root):
    facts, found = _check(con, engine_root, "preopen_not_voided")
    assert found == []
    assert facts["by_status"] == {"completed": 2}

    con.execute("UPDATE p15_preopen_runs SET status = 'unavailable', "
                "reason = 'pre-open evidence is invalid' WHERE session_date = ?", [FRIDAY])
    con.execute("DELETE FROM p15_preopen_runs WHERE session_date = ?", [DAY_ZERO])
    con.execute("INSERT INTO p15_preopen_runs VALUES (9, '2026-10-12', 'running', NULL, "
                "'2026-10-12 13:05:00', NULL)")
    facts, found = _check(con, engine_root, "preopen_not_voided")
    assert _classes(found) == {("voided", f"preopen {FRIDAY}"), ("missed", f"preopen {DAY_ZERO}"),
                               ("stuck", "preopen 2026-10-12")}
    assert facts["voided_sessions"] == [FRIDAY.isoformat()]
    assert facts["missed_sessions"] == [DAY_ZERO.isoformat()]


def test_experiment_results_finite(con, engine_root):
    assert _check(con, engine_root, "experiment_results_finite")[1] == []
    con.execute("INSERT INTO experiment_results VALUES ('exp', 'abcdef0123456789', 'train', "
                "'2026-10-02', 'nan', 'inf', 0, '{\"t\": NaN}')")
    _facts, found = _check(con, engine_root, "experiment_results_finite")
    subject = "exp abcdef012345 train 2026-10-02"
    assert _classes(found) == {("nonfinite_column", subject), ("nonfinite_meta", subject)}
    assert found[0]["detail"]["columns"] == ["mean_ret", "sharpe_annual"]


def test_walkforward_results_finite(con, engine_root):
    facts, found = _check(con, engine_root, "walkforward_results_finite")
    assert (facts["files"], found) == (2, [])
    results = engine_root / "data" / "reports" / "walkforward" / "results"
    (results / "beta.json").write_text(
        '{"folds": [{"train": {"sharpe": NaN, "worst_month": -Infinity}}]}')
    (engine_root / "data" / "reports" / "experiments" / "exp" / "result.json").write_text("{")
    facts, found = _check(con, engine_root, "walkforward_results_finite")
    assert _classes(found) == {
        ("nonfinite", "walkforward:results:beta $.folds[0].train.sharpe"),
        ("nonfinite", "walkforward:results:beta $.folds[0].train.worst_month"),
        ("unreadable", "experiments:exp:result")}
    assert facts["files_with_nonfinite"] == 2


def test_missing_table_is_an_error_not_a_pass(con, engine_root):
    con.execute("DROP TABLE p15_preopen_runs")
    ctx = registry.Context(con=con, snapshot_as_of=AS_OF, engine_root=engine_root)
    result = registry.evaluate(ctx, [], today=AS_OF.date())
    assert result["invariants"]["preopen_not_voided"]["status"] == "error"
    assert result["status"] == "error" and registry.exit_code(result) == 3


def _baseline(tmp_path, *entries) -> list[dict]:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schema_version": 1, "exceptions": list(entries)}))
    return registry.load_baseline(path)


def test_baseline_accepts_by_class_or_subject_until_it_expires(con, engine_root, tmp_path):
    con.execute("UPDATE p15_preopen_runs SET status = 'unavailable' WHERE session_date = ?",
                [FRIDAY])
    entry = {"invariant": "preopen_not_voided", "class": "voided", "owner": "orchestrator",
             "reason": "historical void", "expires": "2026-10-20", "through": "2026-10-16"}
    ctx = registry.Context(con=con, snapshot_as_of=AS_OF, engine_root=engine_root)
    accepted = registry.evaluate(ctx, _baseline(tmp_path, entry), today=date(2026, 10, 20))
    assert accepted["status"] == "pass"
    assert accepted["invariants"]["preopen_not_voided"]["baselined_count"] == 1

    expired = registry.evaluate(ctx, _baseline(tmp_path, entry), today=date(2026, 10, 21))
    item = expired["invariants"]["preopen_not_voided"]
    assert expired["status"] == "regression" and registry.exit_code(expired) == 2
    assert item["regressions"][0]["expired_exception"] == 0
    assert expired["baseline"]["expired"][0]["owner"] == "orchestrator"

    narrow = {**entry, "through": "2026-10-15"}
    assert registry.evaluate(ctx, _baseline(tmp_path, narrow),
                             today=date(2026, 10, 20))["status"] == "regression"
    by_subject = {key: value for key, value in entry.items() if key != "class"}
    by_subject["subjects"] = [f"preopen {FRIDAY}"]
    assert registry.evaluate(ctx, _baseline(tmp_path, by_subject),
                             today=date(2026, 10, 20))["status"] == "pass"


@pytest.mark.parametrize("bad", [
    {"invariant": "preopen_not_voided", "class": "voided", "reason": "x", "expires": "2026-11-01"},
    {"invariant": "preopen_not_voided", "class": "voided", "owner": "o", "reason": "x"},
    {"invariant": "preopen_not_voided", "owner": "o", "reason": "x", "expires": "2026-11-01"},
    {"invariant": "invented", "class": "x", "owner": "o", "reason": "x", "expires": "2026-11-01"},
    {"invariant": "preopen_not_voided", "class": "voided", "owner": "o", "reason": "x",
     "expires": "soon"},
    {"invariant": "preopen_not_voided", "subjects": [], "owner": "o", "reason": "x",
     "expires": "2026-11-01"},
    {"invariant": "preopen_not_voided", "class": "voided", "owner": "o", "reason": "x",
     "expires": "2026-11-01", "note": "unknown key"},
])
def test_baseline_entries_need_owner_reason_expiry_and_a_narrow_match(tmp_path, bad):
    with pytest.raises(ValueError):
        _baseline(tmp_path, bad)


def test_constants_match_their_owners():
    import engine.actions as actions
    from sim import costs, p15_books

    assert math.isclose(market_data.TOL_LOG, actions.TOL_LOG)
    assert math.isclose(market_data.MIN_SEPARATION_LOG, actions.MIN_SEPARATION_LOG)
    assert market_data.BREAK_NEAR_EX_SESSIONS == actions.BREAK_NEAR_EX_SESSIONS
    assert market_data.RECORDED_NEAR_DAYS == actions.TRIPWIRE_NEAR_DAYS
    assert books.P15_BOOK_IDS == p15_books.BOOK_IDS
    assert set(books.P15_AI_BOOK_IDS) < set(p15_books.BOOK_IDS)
    assert books.FEE_PROFILE in costs.PROFILES
