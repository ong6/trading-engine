"""Point-in-time universe, liquidity and screen rows for one replay session.

Production fills these tables from live paths: ``engine.universe.sync_universe``
(today's NASDAQ directory, wall-clock ``added``), ``engine.collect``'s liquidity
refresh and ``engine.screen._run`` (which also writes reports, EOD files and
reads the owner's watchlist).  Replay derives the same rows from the private,
already as-of ``prices`` table only:

* membership: a ticker is a member on D only if its first visible bar is on or
  before D; it is ``active`` while it has a visible bar within the screen's
  staleness window (``engine.screen.stale_cutoff``).  Rows are never deleted, so
  delisted names stay in history.
* liquidity: ``engine.collect.liquid_flags`` + ``apply_liquid_flags`` unchanged.
* screen: ``engine.screen`` eligibility, bar pull and per-ticker metrics, with the
  ranking/template/new_today rules of ``engine.screen._run`` (screen.py:535-562)
  and its ``screen_results`` insert (screen.py:610-619), minus file side effects.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping

import numpy as np
import pandas as pd

from engine import collect, screen
from engine.lib import db
from engine.lib import leverage as lev

_SCREEN_COLUMNS = (
    "run_date", "ticker", "close", "rs_rank", "template_score", "passes_template",
    "dist_50d", "dist_200d", "off_52w_low", "off_52w_high", "base_tight", "vol_dryup",
    "new_today", "universe_policy",
)


def _membership(con, session: date, securities: Mapping[str, Mapping]) -> int:
    cutoff = screen.stale_cutoff(con, session)
    frame = con.execute(
        "SELECT ticker,MIN(date) AS added,MAX(date)>=? AS active "
        "FROM prices WHERE date<=? GROUP BY ticker ORDER BY ticker",
        [cutoff, session],
    ).fetch_df()
    frame["etf"] = [securities.get(ticker, {}).get("etf") for ticker in frame["ticker"]]
    frame["name"] = [securities.get(ticker, {}).get("name") for ticker in frame["ticker"]]
    frame["exchange"] = [
        securities.get(ticker, {}).get("exchange") for ticker in frame["ticker"]
    ]
    with db.registered_frame(con, "_replay_members", frame):
        con.execute(
            "INSERT INTO universe (ticker,yf_ticker,name,exchange,etf,member,added,active) "
            "SELECT m.ticker,m.ticker,m.name,m.exchange,m.etf,NULL,m.added,m.active "
            "FROM _replay_members m WHERE m.ticker NOT IN (SELECT ticker FROM universe)"
        )
        con.execute(
            "UPDATE universe u SET active=m.active FROM _replay_members m "
            "WHERE u.ticker=m.ticker"
        )
        con.execute(
            "UPDATE universe SET active=FALSE "
            "WHERE ticker NOT IN (SELECT ticker FROM _replay_members)"
        )
    return int(frame["active"].sum())


def _screen(con, session: date) -> int:
    if con.execute(
        "SELECT COUNT(*) FROM screen_results WHERE run_date=?", [session]
    ).fetchone()[0]:
        return 0
    eligible, _stale, _short, _phantom = screen.classify_universe(
        con, session, screen.stale_cutoff(con, session)
    )
    if not eligible:
        return 0
    bars = screen.pull_bars(con, session, eligible)
    res = pd.DataFrame.from_records(
        [screen._compute_ticker(ticker, group) for ticker, group in bars.groupby(
            "ticker", sort=False
        )]
    )
    pct = res["rs_raw"].rank(method="average", pct=True)
    res["rs_rank"] = np.clip(np.round(pct * 99), 1, 99).fillna(1).astype(int)
    res["c8"] = res["rs_rank"] >= 70
    checks = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"]
    res["template_score"] = res[checks].sum(axis=1).astype(int)
    res["passes_template"] = res["template_score"] == 8
    prior_run = con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date<?", [session]
    ).fetchone()[0]
    prior_pass = set() if prior_run is None else {
        row[0] for row in con.execute(
            "SELECT ticker FROM screen_results WHERE run_date=? AND passes_template=TRUE",
            [prior_run],
        ).fetchall()
    }
    res["new_today"] = (res["passes_template"] & ~res["ticker"].isin(prior_pass)) & (
        prior_run is not None
    )
    res["run_date"] = session
    res["universe_policy"] = lev.DEFAULT_POLICY
    with db.registered_frame(con, "_replay_screen", res[list(_SCREEN_COLUMNS)]):
        con.execute(
            f"INSERT INTO screen_results ({','.join(_SCREEN_COLUMNS)}) "
            f"SELECT {','.join(_SCREEN_COLUMNS)} FROM _replay_screen"
        )
    return len(res)


def build_session_universe(
    con, session: date, *, securities: Mapping[str, Mapping] | None = None
) -> dict:
    """Write D's point-in-time universe, liquidity flags and screen from private prices.

    Call after D's close is materialized and before scoring D, as production's
    nightly collect -> screen -> score order does.  ``securities`` supplies static
    ticker metadata (``etf``, ``name``, ``exchange``); nothing is inferred.
    """
    if type(session) is not date:
        raise ValueError("invalid_replay_universe_session")
    db.init_screen_policy_schema(con)
    if con.execute("SELECT 1 FROM prices WHERE date<=? LIMIT 1", [session]).fetchone() is None:
        return {"active": 0, "liquid": 0, "screened": 0}
    active = _membership(con, session, securities or {})
    liquidity = collect.apply_liquid_flags(
        con, collect.liquid_flags(con, as_of=session), dry_run=False
    )
    con.execute(
        "INSERT OR IGNORE INTO universe_snapshot "
        "(snapshot_date,ticker,name,exchange,etf,member,active,liquid) "
        "SELECT ?,ticker,name,exchange,etf,member,active,liquid FROM universe",
        [session],
    )
    return {"active": active, "liquid": liquidity["liquid_after"], "screened": _screen(con, session)}
