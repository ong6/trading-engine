"""Screen eligibility: the as-of bar must be a REAL bar (BUILDLOG 2026-08-20c).

TALK passed the live screen on 2026-08-17 (rs_rank 85) on a zero-volume phantom
bar — yfinance kept repeating its 08-14 close as o=h=l=c / volume 0 after the
name stopped trading. Live (engine/screen.py) and replay
(farm/backtest/hist_screen.py) must both skip such names, and staleness is
keyed on the last TRADED bar, matching league.md's stale-mark rule.
"""
from __future__ import annotations

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
