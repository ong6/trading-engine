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
                         "high": [13.5, 6.5, 6.1], "low": [13.0, 6.49, 6.0],
                         "close": [13.44, 6.492, 6.036], "volume": [1000, 5000, 4000]})


def test_unknown_basis_preserves_target_rows_and_evidence(con):
    _universe(con)
    insert_bars(con, "JEM", D, close=[161.28, 6.492, 6.036])   # 12x on the first row
    insert_bars(con, "NBR", D, close=50.0)
    out = rt.refetch(con, "JEM", apply=True, force=False, fetch=_fresh, show_dates=[])
    assert out["rows_before"] == 3 and out["rows_after"] == 3
    assert con.execute("SELECT close FROM prices WHERE ticker='JEM' AND date=?",
                       [D[0]]).fetchone()[0] == pytest.approx(161.28)
    assert out["status"] == "withheld" and out["rows_written"] == 0
    assert con.execute("SELECT count(*) FROM price_observation_rejects WHERE reason='basis_unverified'").fetchone() == (3,)
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


def _continuous(_yf, canon):
    """The source's restated 1:12 series: continuous across all three sessions."""
    return pd.DataFrame({"ticker": canon, "date": D, "open": [13.4, 13.5, 13.6],
                         "high": [13.5, 13.6, 13.7], "low": [13.3, 13.4, 13.5],
                         "close": [13.44, 13.5, 13.6], "volume": [1000, 5000, 4000]})


def _stamped_jem(con, first):
    _universe(con)
    con.execute("ALTER TABLE prices ADD COLUMN IF NOT EXISTS first_fetched_at TIMESTAMP")
    insert_bars(con, "JEM", D[:2], close=[161.28, 13.5])           # D[2] is new
    con.execute("UPDATE prices SET fetched_at = TIMESTAMP '2026-07-16 22:30', "
                "first_fetched_at = ?", [first])


def test_keeps_first_fetch_stamps_and_records_the_split_like_rewrite(con):
    """DXJ/JEM: the old DELETE + upsert reset every row's first_fetched_at, and the
    rescaling left no trace for the actions fetch or the reconciler. With the 1:12
    split on record the replacement is promoted: existing dates keep their first
    stamp, the new date is stamped now, and one split_like_rewrite row is kept."""
    from datetime import datetime

    from engine import actions
    from engine.lib import db

    first = datetime(2026, 7, 9, 22, 30)
    _stamped_jem(con, first)
    db.init_actions_schema(con)
    con.execute("INSERT INTO corporate_actions VALUES ('JEM', ?, 'split', ?, 'yfinance', now())",
                [D[0], 1 / 12])

    out = rt.refetch(con, "JEM", apply=True, force=False, fetch=_continuous, show_dates=[])

    assert out.get("status") != "withheld" and out["rows_written"] == 3
    stamps = dict(con.execute("SELECT date, first_fetched_at FROM prices "
                              "WHERE ticker = 'JEM'").fetchall())
    assert stamps[D[0]] == first and stamps[D[1]] == first
    assert stamps[D[2]] > first                                    # stamped now
    assert out["split_like_rewrite"] is True
    (rewrite,) = actions._rewrites(con, "JEM")
    assert rewrite["dates"] == [D[0].isoformat()]
    assert rewrite["ratio"] == pytest.approx(12.0)


def test_withheld_replacement_keeps_stamps_and_leaves_no_rewrite_row(con):
    """No split on record: the 12x replacement is withheld as basis_unverified
    (revision-15 price admission), so nothing is rewritten, the stored stamps are
    untouched and no split_like_rewrite row claims a rescale that never landed."""
    from datetime import datetime

    from engine import actions

    first = datetime(2026, 7, 9, 22, 30)
    _stamped_jem(con, first)

    out = rt.refetch(con, "JEM", apply=True, force=False, fetch=_continuous, show_dates=[])

    assert out["status"] == "withheld" and out["split_like_rewrite"] is False
    assert dict(con.execute("SELECT date, first_fetched_at FROM prices "
                            "WHERE ticker = 'JEM'").fetchall()) == {D[0]: first, D[1]: first}
    assert actions._rewrites(con, "JEM") == []
