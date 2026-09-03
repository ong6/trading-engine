"""engine/refetch_ticker.py — replace one ticker's history, nothing else."""
from datetime import date

import pandas as pd
import pytest

from engine import refetch_ticker as rt
from tests.conftest import insert_bars

D = [date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 13)]


def _universe(con):
    con.execute("CREATE TABLE IF NOT EXISTS universe (ticker VARCHAR PRIMARY KEY, "
                "yf_ticker VARCHAR)")
    con.execute("INSERT INTO universe VALUES ('JEM', 'JEM'), ('NBR', 'NBR')")


def _fresh(_yf, canon):
    return pd.DataFrame({"ticker": canon, "date": D, "open": [13.0, 6.5, 6.0],
                         "high": [13.0, 6.5, 6.0], "low": [13.0, 6.5, 6.0],
                         "close": [13.44, 6.492, 6.036], "volume": [1000, 5000, 4000]})


def test_replaces_only_target_rows(con):
    _universe(con)
    insert_bars(con, "JEM", D, close=[161.28, 6.492, 6.036])   # 12x on the first row
    insert_bars(con, "NBR", D, close=50.0)
    out = rt.refetch(con, "JEM", apply=True, force=False, fetch=_fresh, show_dates=[])
    assert out["rows_before"] == 3 and out["rows_after"] == 3
    assert con.execute("SELECT close FROM prices WHERE ticker='JEM' AND date=?",
                       [D[0]]).fetchone()[0] == pytest.approx(13.44)
    assert con.execute("SELECT COUNT(*) FROM prices WHERE ticker='NBR' AND close=50").fetchone()[0] == 3


def test_dry_run_writes_nothing(con):
    _universe(con)
    insert_bars(con, "JEM", D, close=[161.28, 6.492, 6.036])
    rt.refetch(con, "JEM", apply=False, force=False, fetch=_fresh, show_dates=[])
    assert con.execute("SELECT close FROM prices WHERE ticker='JEM' AND date=?",
                       [D[0]]).fetchone()[0] == pytest.approx(161.28)


def test_refuses_open_position_without_force(con):
    _universe(con)
    insert_bars(con, "JEM", D, close=10.0)
    con.execute("INSERT INTO sim_positions (portfolio_id, ticker, qty, avg_cost) "
                "VALUES ('b', 'JEM', 5, 10)")
    with pytest.raises(SystemExit):
        rt.refetch(con, "JEM", apply=True, force=False, fetch=_fresh, show_dates=[])
    rt.refetch(con, "JEM", apply=True, force=True, fetch=_fresh, show_dates=[])


def test_aborts_on_suspicious_replacement(con):
    _universe(con)
    insert_bars(con, "JEM", D, close=10.0)

    def bad(_yf, canon):
        df = _fresh(_yf, canon)
        df.loc[1, "volume"] = 0          # a >50% drop on a zero-volume bar
        return df

    with pytest.raises(SystemExit):
        rt.refetch(con, "JEM", apply=True, force=False, fetch=bad, show_dates=[])
