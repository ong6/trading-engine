"""Known-answer and availability tests for retained P16 factor inputs."""
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from engine.lib.db import init_mining_schema
from engine.p16_features import exposure_snapshot, session_dates

MARKET_DATE = date(2024, 7, 5)
CUTOFF = datetime(2024, 7, 6, 2, tzinfo=timezone.utc)


def _history(con):
    dates = session_dates(MARKET_DATE, 253)
    spy_returns = np.tile([-0.01, 0.02, 0.005], 84)
    spy = 100 * np.r_[1, np.cumprod(1 + spy_returns)]
    stock = 40 * np.r_[1, np.cumprod(1 + 2 * spy_returns)]
    rows = []
    for ticker, closes in (("SPY", spy), ("AAA", stock)):
        for day, close in zip(dates, closes, strict=True):
            rows.append((ticker, day, close, close * 1.01, close * 0.99,
                         close, 1_000_000, datetime.combine(day, datetime.min.time())
                         + timedelta(hours=21)))
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?)", rows,
    )
    return dates, stock, spy_returns


def test_factors_match_known_returns_and_beta(con):
    dates, closes, spy_returns = _history(con)
    report = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    item = report["candidates"][0]
    assert item["status"] == "available" and item["sector"] == "unknown"
    assert item["exposures"] == pytest.approx({
        "momentum_12_1": closes[-22] / closes[-253] - 1,
        "return_21": closes[-1] / closes[-22] - 1,
        "return_1": 2 * spy_returns[-1],
        "log_adv20": np.log(np.median(closes[-21:-1]) * 1_000_000),
        "beta60": 2.0,
        "vol60": np.std(2 * spy_returns[-60:], ddof=1),
    })
    assert report["price_basis"] == "split_adjusted_price_v1"
    assert dates[-2] == date(2024, 7, 3)  # July 4 is not an observed-price shortcut.


def test_future_and_phantom_bars_never_repair_missing_exposure(con):
    dates, _, _ = _history(con)
    con.execute("UPDATE prices SET fetched_at=? WHERE ticker='AAA' AND date=?",
                [CUTOFF.replace(tzinfo=None) + timedelta(seconds=1), dates[-22]])
    before = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    item = before["candidates"][0]
    assert item["status"] == "unavailable"
    assert set(item["missing_exposures"]) == {"momentum_12_1", "return_21", "beta60", "vol60"}
    con.execute("UPDATE prices SET close=999999 WHERE ticker='AAA' AND date=?", [dates[-22]])
    after = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    assert before == after
    con.execute("UPDATE prices SET open=close,high=close,low=close WHERE ticker='AAA' AND date=?",
                [dates[-2]])
    phantom = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    assert "return_1" in phantom["candidates"][0]["missing_exposures"]


def test_missing_names_and_benchmark_remain_explicit(con):
    dates, _, _ = _history(con)
    con.execute("DELETE FROM prices WHERE ticker='SPY' AND date=?", [dates[-20]])
    report = exposure_snapshot(con, ["NEW", "AAA", "AAA"], MARKET_DATE,
                               information_cutoff_at=CUTOFF)
    aaa, new = report["candidates"]
    assert aaa["ticker"] == "AAA" and aaa["missing_exposures"] == ["beta60"]
    assert new["ticker"] == "NEW" and len(new["missing_exposures"]) == 6
    assert new["real_bar_count"] == 0


def test_sector_snapshot_is_availability_bounded_and_latest_null_wins(con):
    _history(con)
    init_mining_schema(con)
    con.execute(
        "INSERT INTO fundamentals(ticker,as_of,sector,source,fetched_at) VALUES "
        "('AAA','2024-07-01',' Technology ','old',?),"
        "('AAA','2024-07-02',NULL,'latest',?),"
        "('AAA','2024-07-03','Energy','future',?)",
        [CUTOFF.replace(tzinfo=None) - timedelta(days=2),
         CUTOFF.replace(tzinfo=None) - timedelta(days=1),
         CUTOFF.replace(tzinfo=None) + timedelta(seconds=1)],
    )
    result = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    item = result["candidates"][0]
    assert item["sector"] == "unknown"
    assert item["sector_source"] == {
        "sector": "unknown", "as_of": "2024-07-02",
        "fetched_at": (CUTOFF.replace(tzinfo=None) - timedelta(days=1)).isoformat(),
        "source": "latest",
    }


def test_missing_interior_session_invalidates_full_momentum_history(con):
    dates, _, _ = _history(con)
    con.execute("DELETE FROM prices WHERE ticker='AAA' AND date=?", [dates[100]])
    item = exposure_snapshot(con, ["AAA"], MARKET_DATE,
                             information_cutoff_at=CUTOFF)["candidates"][0]
    assert item["exposures"]["momentum_12_1"] is None
    assert item["exposures"]["return_21"] is not None


def test_bar_source_is_part_of_the_retained_snapshot_identity(con):
    _history(con)
    before = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    con.execute("UPDATE prices SET source='alternate' WHERE ticker='AAA'")
    after = exposure_snapshot(con, ["AAA"], MARKET_DATE, information_cutoff_at=CUTOFF)
    assert before["source_bars_sha256"] != after["source_bars_sha256"]
    assert before["snapshot_sha256"] != after["snapshot_sha256"]


def test_naive_cutoff_and_non_session_are_rejected(con):
    with pytest.raises(ValueError, match="timezone"):
        exposure_snapshot(con, [], MARKET_DATE, information_cutoff_at=CUTOFF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="session"):
        exposure_snapshot(con, [], date(2024, 7, 4), information_cutoff_at=CUTOFF)


def test_eod_factors_require_the_actual_session_close(con):
    with pytest.raises(ValueError, match="not closed"):
        exposure_snapshot(con, [], MARKET_DATE,
                          information_cutoff_at=datetime(2024, 7, 5, 19, 59, tzinfo=timezone.utc))
    # The July 3 early close is 13:00 ET, not 16:00 ET.
    result = exposure_snapshot(con, [], date(2024, 7, 3),
                               information_cutoff_at=datetime(2024, 7, 3, 17, tzinfo=timezone.utc))
    assert result["candidates"] == []
