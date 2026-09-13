"""Screen eligibility: the as-of bar must be a REAL bar (BUILDLOG 2026-08-20c).

TALK passed the live screen on 2026-08-17 (rs_rank 85) on a zero-volume phantom
bar — yfinance kept repeating its 08-14 close as o=h=l=c / volume 0 after the
name stopped trading. Live (engine/screen.py) and replay
(farm/backtest/hist_screen.py) must both skip such names, and staleness is
keyed on the last TRADED bar, matching league.md's stale-mark rule.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from engine import screen
from engine.lib import db
from farm.backtest import hist_screen
from tests.conftest import insert_bars, sessions

# 300 sessions -> comfortably above MIN_BARS (253) for every name.
DAYS = sessions(date(2023, 5, 1), date(2024, 7, 31))
assert len(DAYS) > screen.MIN_BARS + 20
LAST = DAYS[-1]


def _universe(con, *tickers):
    db.init_schema(con)  # universe / universe_snapshot / screen_results (prices exists)
    for t in tickers:
        con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid) "
                    "VALUES (?, ?, TRUE, TRUE)", [t, t])


def _rising(n: int, start=50.0, step=0.2) -> list[float]:
    return [start + i * step for i in range(n)]


def _real_series(con, ticker: str, dates=DAYS):
    closes = _rising(len(dates))
    insert_bars(con, ticker, dates, open_=closes, close=closes,
                high=[c + 0.5 for c in closes], low=[c - 0.5 for c in closes],
                volume=1_000_000)


def _phantom_tail(con, ticker: str, n_phantom: int, *, volume=0):
    """Real bars, then `n_phantom` dead quotes (o=h=l=c at the last real close)."""
    real = DAYS[:-n_phantom]
    _real_series(con, ticker, real)
    last_close = _rising(len(real))[-1]
    insert_bars(con, ticker, DAYS[-n_phantom:], open_=last_close, close=last_close,
                high=last_close, low=last_close, volume=volume)


@pytest.fixture
def universe_con(con):
    return con


def test_zero_volume_asof_bar_is_skipped_as_phantom(universe_con):
    con = universe_con
    _universe(con, "REAL", "TALK")
    _real_series(con, "REAL")
    _phantom_tail(con, "TALK", 1)            # the 2026-08-17 shape
    cutoff = screen.stale_cutoff(con, LAST)
    eligible, n_stale, n_short, n_phantom = screen.classify_universe(con, LAST, cutoff)
    assert eligible == ["REAL"]
    assert (n_stale, n_short, n_phantom) == (0, 0, 1)


def test_dead_quote_with_nonzero_volume_is_also_phantom(universe_con):
    con = universe_con
    _universe(con, "DEAD")
    _phantom_tail(con, "DEAD", 1, volume=100)   # o=h=l=c but volume > 0
    cutoff = screen.stale_cutoff(con, LAST)
    eligible, n_stale, n_short, n_phantom = screen.classify_universe(con, LAST, cutoff)
    assert eligible == [] and n_phantom == 1


def test_staleness_is_keyed_on_last_traded_bar(universe_con):
    con = universe_con
    _universe(con, "EA")
    # 5 phantom sessions: last TRADED bar is > STALE_TRADING_DAYS old even
    # though MAX(date) is the screen date itself -> stale, not merely phantom.
    _phantom_tail(con, "EA", screen.STALE_TRADING_DAYS + 2)
    cutoff = screen.stale_cutoff(con, LAST)
    eligible, n_stale, n_short, n_phantom = screen.classify_universe(con, LAST, cutoff)
    assert eligible == [] and n_stale == 1 and n_phantom == 0


def test_legit_zero_volume_day_in_history_does_not_disqualify(universe_con):
    """A thin name with an OLD zero-volume day still screens when its as-of
    bar is real: volume = 0 alone is not proof of a phantom."""
    con = universe_con
    _universe(con, "THIN")
    closes = _rising(len(DAYS))
    vols = [1_000_000] * len(DAYS)
    vols[-30] = 0
    insert_bars(con, "THIN", DAYS, open_=closes, close=closes,
                high=[c + 0.5 for c in closes], low=[c - 0.5 for c in closes], volume=vols)
    cutoff = screen.stale_cutoff(con, LAST)
    eligible, *_ = screen.classify_universe(con, LAST, cutoff)
    assert eligible == ["THIN"]


def test_hist_screen_agrees_with_live_on_phantom_asof_bar(universe_con):
    con = universe_con
    _universe(con, "REAL", "TALK")
    _real_series(con, "REAL")
    _phantom_tail(con, "TALK", 1)
    # Both names clear the `prices` membership floor (close ~110 x 1M shares).
    n = hist_screen.screen_sessions(con, [DAYS[-2], LAST], membership="prices",
                                    passing_only=False, table="screen_results",
                                    verbose=False)
    got = {(r[0], r[1]) for r in con.execute(
        "SELECT run_date, ticker FROM screen_results").fetchall()}
    assert (DAYS[-2], "TALK") in got      # its last REAL bar is the as-of bar there
    assert (LAST, "TALK") not in got      # phantom as-of bar -> dropped, like live
    assert (LAST, "REAL") in got
    assert n == 3


def test_hist_screen_drops_temporary_tables_after_intermediate_failure(
    universe_con, monkeypatch
):
    con = universe_con
    _universe(con, "REAL")
    _real_series(con, "REAL")
    real_execute = con.execute

    class ConnectionProxy:
        def __getattr__(self, name):
            return getattr(con, name)

        def execute(self, sql, parameters=None):
            if "CREATE OR REPLACE TEMP TABLE _hs_prev" in sql:
                raise RuntimeError("injected historical-screen failure")
            if parameters is None:
                return real_execute(sql)
            return real_execute(sql, parameters)

    with pytest.raises(RuntimeError, match="injected historical-screen failure"):
        hist_screen.screen_sessions(
            ConnectionProxy(),
            [LAST],
            membership="prices",
            passing_only=False,
            table="screen_results",
            verbose=False,
        )

    remaining = {
        row[0]
        for row in real_execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert remaining.isdisjoint(hist_screen.TEMP_TABLES)
    assert real_execute("SELECT 1").fetchone() == (1,)


def test_eod_export_publishes_atomically(con, tmp_path, monkeypatch):
    insert_bars(con, "AAA", DAYS[-2:], close=[10.0, 11.0])
    atomic_paths = []
    real_atomic_write = screen.rsc.write_text_atomic

    def recording_atomic_write(path, text):
        atomic_paths.append(path)
        real_atomic_write(path, text)

    monkeypatch.setattr(screen.rsc, "write_text_atomic", recording_atomic_write)

    assert screen.write_eod(con, LAST, ["AAA"], tmp_path) == []
    target = tmp_path / "AAA.csv"
    assert atomic_paths == [target]
    assert target.read_text().startswith("date,open,high,low,close,volume\n")
    assert list(tmp_path.glob("AAA.csv.*.tmp")) == []


def test_existing_screen_summary_is_restored_without_rewriting_rows(
    con, tmp_path, monkeypatch
):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    con.executemany(
        "INSERT INTO screen_results "
        "(run_date,ticker,rs_rank,template_score,passes_template,new_today,universe_policy) "
        "VALUES (DATE '2026-09-04',?,?,?,?,?,?)",
        [
            ("AAA", 99, 8, True, False, "all"),
            ("BBB", 50, 6, False, False, "all"),
        ],
    )
    screens = tmp_path / "screens"
    screens.mkdir()
    report = screens / "2026-09-04.md"
    report.write_text(
        "# Screen — 2026-09-04  (universe: 2 · passing: 1 · new today: 0 · "
        "regime: risk-on · policy: all)\n\nbody\n"
    )
    (screens / "latest.md").write_text("stale")
    (tmp_path / "_meta.json").write_text(
        json.dumps({"fundamentals": {"last_run": "preserved"}, "skipped_stale": 99})
    )
    insert_bars(con, "AAA", [date(2026, 9, 4)], close=[10.0])
    monkeypatch.setattr(screen, "WATCHLIST_PATH", tmp_path / "missing-watchlist.md")

    screen.republish_existing_summary(con, date(2026, 9, 4), tmp_path)

    assert (screens / "latest.md").read_text() == report.read_text()
    assert con.execute("SELECT COUNT(*) FROM screen_results").fetchone()[0] == 2
    meta = json.loads((tmp_path / "_meta.json").read_text())
    assert meta["screen_date"] == "2026-09-04"
    assert meta["regime"] == "risk-on"
    assert meta["screened"] == 2
    assert meta["passing_count"] == 1
    assert meta["new_today_count"] == 0
    assert meta["last_screen"] is None
    assert meta["screen_metadata_source"] == "existing-artifacts"
    assert meta["skipped_stale"] is None
    assert meta["fundamentals"] == {"last_run": "preserved"}
    assert (screens / "2026-09-04.csv").read_text().startswith("run_date,ticker")
    assert (tmp_path / "eod" / "AAA.csv").exists()


def test_existing_screen_summary_rejects_report_database_mismatch(con, tmp_path):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    con.execute(
        "INSERT INTO screen_results "
        "(run_date,ticker,rs_rank,template_score,passes_template,new_today,universe_policy) "
        "VALUES (DATE '2026-09-04','AAA',99,8,TRUE,FALSE,'all')"
    )
    screens = tmp_path / "screens"
    screens.mkdir()
    (screens / "2026-09-04.md").write_text(
        "# Screen — 2026-09-04  (universe: 2 · passing: 1 · new today: 0 · "
        "regime: risk-on · policy: all)\n"
    )

    with pytest.raises(ValueError, match="does not match stored rows"):
        screen.republish_existing_summary(con, date(2026, 9, 4), tmp_path)


def test_skip_with_rows_but_no_recovery_anchor_preserves_append_only_rows(con, tmp_path):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    con.execute(
        "INSERT INTO screen_results "
        "(run_date,ticker,rs_rank,template_score,passes_template,new_today,universe_policy) "
        "VALUES (DATE '2026-09-04','AAA',99,8,TRUE,FALSE,'all')"
    )
    before = con.execute(
        "SELECT * FROM screen_results WHERE run_date = DATE '2026-09-04'"
    ).fetchall()

    assert screen._run(
        con,
        tmp_path,
        "2026-09-04",
        rerun=False,
        skip_if_done=True,
        universe_policy="all",
    ) == 1

    assert con.execute(
        "SELECT * FROM screen_results WHERE run_date = DATE '2026-09-04'"
    ).fetchall() == before
    assert not (tmp_path / "screens" / "2026-09-04.md").exists()
    assert not (tmp_path / "_meta.json").exists()


def test_no_eligible_names_does_not_close_borrowed_connection(con, tmp_path):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    insert_bars(con, "SPY", [date(2026, 9, 4)])

    assert screen._run(
        con,
        tmp_path,
        "2026-09-04",
        rerun=False,
        universe_policy="all",
    ) == 1
    assert con.execute("SELECT 1").fetchone() == (1,)


def test_screen_publishes_recovery_anchor_before_row_commit(
    universe_con, tmp_path, monkeypatch
):
    con = universe_con
    _universe(con, "REAL")
    _real_series(con, "REAL")
    anchor = tmp_path / "screens" / f"{LAST.isoformat()}.md"
    real_execute = con.execute

    class ConnectionProxy:
        def __getattr__(self, name):
            return getattr(con, name)

        def execute(self, sql, parameters=None):
            if sql.startswith("INSERT INTO screen_results SELECT"):
                assert anchor.exists()
                raise RuntimeError("injected row-commit failure")
            if parameters is None:
                return real_execute(sql)
            return real_execute(sql, parameters)

    monkeypatch.setattr(screen, "WATCHLIST_PATH", tmp_path / "missing-watchlist.md")

    with pytest.raises(RuntimeError, match="injected row-commit failure"):
        screen._run(
            ConnectionProxy(),
            tmp_path,
            LAST.isoformat(),
            rerun=False,
            universe_policy="all",
        )

    assert anchor.read_text().startswith(f"# Screen — {LAST.isoformat()}")
    assert real_execute(
        "SELECT COUNT(*) FROM screen_results WHERE run_date = ?", [LAST]
    ).fetchone()[0] == 0


def test_screen_run_closes_connection_on_schema_failure(monkeypatch, tmp_path):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(screen.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(
        screen.db,
        "init_schema",
        lambda _con: (_ for _ in ()).throw(RuntimeError("injected schema failure")),
    )

    with pytest.raises(RuntimeError, match="injected schema failure"):
        screen.run("unused", tmp_path, None, False)
    assert connection.closed is True
