"""Fill model: next-open only, slippage direction, liquidity guard, no invented bars."""
from datetime import date

import pytest

from sim import fills
from tests.conftest import SESSIONS, insert_bars

# 30 history bars then the fill bar. $vol per bar = 100 * 1_000_000 = $100M.
HIST = SESSIONS[:30]
SIGNAL = HIST[-1]
FILL = SESSIONS[30]


@pytest.fixture
def liquid(con):
    insert_bars(con, "AAA", HIST + [FILL], open_=100.0, close=100.0, volume=1_000_000)
    return con


# ---------------------------------------------------------------- tiers ---- #
@pytest.mark.parametrize("mdv,half", [
    (None, 25.0), (0.0, 25.0), (4_999_999.0, 25.0), (5_000_000.0, 15.0),
    (19_999_999.0, 15.0), (20_000_000.0, 10.0), (49_999_999.0, 10.0),
    (50_000_000.0, 5.0), (1e12, 5.0),
])
def test_half_spread_tiers(mdv, half):
    assert fills.half_spread_bps(mdv) == half


def test_slippage_is_half_spread_plus_five():
    assert fills.slippage_bps_for(1e9) == 10.0      # max(5,5)+5
    assert fills.slippage_bps_for(None) == 30.0     # 25+5
    assert fills.slippage_bps_for(6_000_000) == 20.0


# ------------------------------------------------------------ look-ahead --- #
def test_same_bar_fill_is_asserted_away(liquid):
    with pytest.raises(AssertionError, match="look-ahead"):
        fills.attempt_fill(liquid, "AAA", "buy", 1, FILL, FILL)


def test_fill_before_signal_is_asserted_away(liquid):
    with pytest.raises(AssertionError):
        fills.attempt_fill(liquid, "AAA", "buy", 1, FILL, SIGNAL)


# ------------------------------------------------------------ direction ---- #
def test_buy_fills_above_open(liquid):
    r = fills.attempt_fill(liquid, "AAA", "buy", 10, SIGNAL, FILL)
    assert r.status == "filled"
    assert r.open_px == 100.0
    assert r.slippage_bps == 10.0
    assert r.fill_px == pytest.approx(100.0 * (1 + 10 / 1e4))
    assert r.fill_px > r.open_px


def test_sell_fills_below_open(liquid):
    r = fills.attempt_fill(liquid, "AAA", "sell", 10, SIGNAL, FILL)
    assert r.status == "filled"
    assert r.fill_px == pytest.approx(100.0 * (1 - 10 / 1e4))
    assert r.fill_px < r.open_px


def test_fill_uses_next_open_not_signal_close(con):
    # Signal-day close 100, next open gaps to 120 -> fill is off 120.
    insert_bars(con, "AAA", HIST, open_=100.0, close=100.0)
    insert_bars(con, "AAA", [FILL], open_=120.0, close=125.0)
    r = fills.attempt_fill(con, "AAA", "buy", 1, SIGNAL, FILL)
    assert r.open_px == 120.0
    assert r.fill_px == pytest.approx(120.0 * 1.001)


# ------------------------------------------------------ liquidity guard ---- #
def test_median_dollar_vol_excludes_fill_bar(con):
    insert_bars(con, "AAA", HIST, open_=100.0, close=100.0, volume=1_000_000)
    insert_bars(con, "AAA", [FILL], open_=100.0, close=100.0, volume=10**9)
    assert fills.median_dollar_vol(con, "AAA", FILL) == pytest.approx(1e8)


def test_median_dollar_vol_none_without_history(con):
    insert_bars(con, "AAA", [FILL])
    assert fills.median_dollar_vol(con, "AAA", FILL) is None


def test_notional_over_one_pct_rejects(liquid):
    # mdv $100M -> cap $1M notional -> 10_001 shares @ 100 is over.
    r = fills.attempt_fill(liquid, "AAA", "buy", 10_001, SIGNAL, FILL)
    assert r.status == "rejected"
    assert r.reject_reason.startswith("illiquid")
    assert r.fill_px is None
    assert r.median_dollar_vol == pytest.approx(1e8)


def test_notional_at_exactly_one_pct_fills(liquid):
    r = fills.attempt_fill(liquid, "AAA", "buy", 10_000, SIGNAL, FILL)
    assert r.status == "filled"


def test_no_history_skips_liquidity_guard_but_uses_worst_tier(con):
    insert_bars(con, "NEW", [FILL], open_=10.0)
    r = fills.attempt_fill(con, "NEW", "buy", 1_000_000, SIGNAL, FILL)
    assert r.status == "filled"
    assert r.slippage_bps == 30.0
    assert r.median_dollar_vol is None


# ------------------------------------------------------------ missing bar -- #
def test_missing_bar_stays_pending_then_rejects_no_bar(con):
    insert_bars(con, "SPY", SESSIONS)                     # the calendar
    insert_bars(con, "HALT", HIST)                        # no bar after SIGNAL
    d1, d2, d3 = SESSIONS[30], SESSIONS[31], SESSIONS[32]
    assert fills.attempt_fill(con, "HALT", "buy", 1, SIGNAL, d1).status == "pending"
    assert fills.attempt_fill(con, "HALT", "buy", 1, SIGNAL, d2).status == "pending"
    r = fills.attempt_fill(con, "HALT", "buy", 1, SIGNAL, d3)
    assert (r.status, r.reject_reason) == ("rejected", "no_bar")


def test_null_open_is_treated_as_missing_bar(con):
    insert_bars(con, "SPY", SESSIONS)
    insert_bars(con, "AAA", HIST)
    con.execute("INSERT INTO prices (ticker, date, open, close, volume) VALUES "
                "('AAA', ?, NULL, 100, 1000)", [FILL])
    assert fills.attempt_fill(con, "AAA", "buy", 1, SIGNAL, FILL).status == "pending"
