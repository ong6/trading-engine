#!/usr/bin/env python
"""Daily earnings-calendar miner (§12.2).

Upcoming earnings dates feed two things: the earnings-risk gate (don't hold a
swing into a print) and event studies later. Dates move as the quarter
approaches, so every pull is its own `as_of`-stamped snapshot and a gate lookup
uses the LATEST snapshot per ticker. A citizen of the §12.7 job queue: the queue
dispatches to `run(params, con, meta_path)`; a `__main__` here runs it standalone.

Universe (v1 boundary — see BUILDLOG): equities with fundamentals coverage
(a `fundamentals` row whose market_cap is non-NULL — i.e. real equities the
weekly fundamentals miner has seen) UNION the latest screen's passers. This
excludes ETFs (no earnings) and dead tickers, keeping a per-name daily pull
bounded. Fallback when the `fundamentals` table is empty (fresh store, fundamentals
not run yet): all liquid, non-ETF names. Stated honestly here and reported in
_meta.json under `universe_source`.

Source: yfinance `Ticker.calendar['Earnings Date']` — one request per name (no
batch API). Returns a list of one date (single/confirmed) or two (an estimate
window); we store each date with is_estimate = (len != 1). Never fabricate a
date: a name that returns no calendar / no date is counted, not stored.

Guardrails: append-only (db.insert_earnings anti-joins on
(ticker, earnings_date, as_of) — a re-run on the same day inserts nothing), polite
per-name pulls (small sleep, one backoff retry then record a gap), honest
_meta.json accounting, resumable (skip names already pulled for today's as_of).
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db  # noqa: E402
from lib import resources as rsc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_META = REPO_ROOT / "data" / "_meta.json"
STORE_DIR = REPO_ROOT / "store"

PER_NAME_SLEEP = 0.4       # politeness pause between per-name .calendar requests
RETRY_SLEEP = 15           # one backoff before recording a name as a gap
FLUSH_EVERY = 25           # insert + checkpoint progress every N names (resumability)


# --------------------------------------------------------------------------- #
# universe selection + resumability
# --------------------------------------------------------------------------- #
def _table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def _select_universe(con, params: dict) -> tuple[list[tuple[str, str]], str]:
    """Return ((canonical, yf) pairs, universe_source label). --tickers overrides;
    else equities-with-fundamentals ∪ latest screen passers, falling back to
    liquid non-ETF names when the fundamentals table is empty."""
    tickers = params.get("tickers")
    if tickers:
        if isinstance(tickers, str):
            tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        rows = con.execute(
            "SELECT ticker, yf_ticker FROM universe WHERE ticker IN "
            f"({','.join(['?'] * len(tickers))})",
            list(tickers),
        ).fetchall()
        found = {tk: (yft or tk) for tk, yft in rows}
        return [(tk, found.get(tk, tk)) for tk in tickers], "explicit-tickers"

    canon: set[str] = set()
    source = "fundamentals-coverage ∪ screen-passers"

    have_fund = _table_exists(con, "fundamentals") and con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE market_cap IS NOT NULL"
    ).fetchone()[0] > 0
    if have_fund:
        # equities the fundamentals miner has seen (latest as_of with real mcap)
        rows = con.execute(
            """
            WITH latest AS (SELECT MAX(as_of) m FROM fundamentals)
            SELECT DISTINCT ticker FROM fundamentals
            WHERE market_cap IS NOT NULL AND as_of = (SELECT m FROM latest)
            """
        ).fetchall()
        canon |= {r[0] for r in rows}
    else:
        # fresh store: fall back to liquid, non-ETF names
        source = "liquid-non-etf (fundamentals empty)"
        rows = con.execute(
            "SELECT ticker FROM universe WHERE liquid = TRUE AND etf = FALSE"
        ).fetchall()
        canon |= {r[0] for r in rows}

    # UNION the latest screen's passers (actionable names), if any
    max_run = con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
    if max_run is not None:
        rows = con.execute(
            "SELECT ticker FROM screen_results WHERE run_date = ? AND passes_template = TRUE",
            [max_run],
        ).fetchall()
        canon |= {r[0] for r in rows}

    if not canon:
        return [], source
    yf_rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE ticker IN "
        f"({','.join(['?'] * len(canon))})",
        list(canon),
    ).fetchall()
    ymap = {tk: (yft or tk) for tk, yft in yf_rows}
    return sorted(((tk, ymap.get(tk, tk)) for tk in canon)), source


def _already_done(con, as_of: date) -> set[str]:
    """Tickers already pulled for this as_of (the resume set). A ticker with any
    row for today's as_of is considered done — including ones that had a date."""
    rows = con.execute(
        "SELECT DISTINCT ticker FROM earnings_calendar WHERE as_of = ?", [as_of]
    ).fetchall()
    return {r[0] for r in rows}


# --------------------------------------------------------------------------- #
# per-name fetch
# --------------------------------------------------------------------------- #
def _fetch_calendar(yf_ticker: str) -> dict | None:
    """One `.calendar` pull with a single backoff retry. Returns the dict, or
    None on hard failure (caller records a gap — never loops)."""
    try:
        return yf.Ticker(yf_ticker).calendar
    except Exception:  # noqa: BLE001 - resilient, retry once
        time.sleep(RETRY_SLEEP)
        try:
            return yf.Ticker(yf_ticker).calendar
        except Exception:  # noqa: BLE001
            return None


def _dates_from_calendar(cal: dict | None) -> tuple[list[date], bool] | None:
    """Extract upcoming earnings dates. Returns (dates, is_estimate) or None when
    there is no usable date. is_estimate = the source gave a window (len != 1)."""
    if not cal or not isinstance(cal, dict):
        return None
    raw = cal.get("Earnings Date")
    if not raw:
        return None
    if not isinstance(raw, list):
        raw = [raw]
    dates: list[date] = []
    for d in raw:
        if isinstance(d, datetime):
            dates.append(d.date())
        elif isinstance(d, date):
            dates.append(d)
    if not dates:
        return None
    return dates, len(dates) != 1


# --------------------------------------------------------------------------- #
# entry point the queue dispatches to
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """Pull upcoming earnings dates for the earnings universe into the
    append-only `earnings_calendar` table, stamped with today's as_of. A re-run
    on the same day is a no-op (resumability skip + insert anti-join).

    params:
      tickers — 'A,B,C' or a list: pull only these (testing).
      limit   — cap to the first N names (fast smoke tests).
    Returns the accounting dict also written under _meta.json 'earnings'.
    """
    params = params or {}
    db.init_mining_schema(con)
    as_of = datetime.now(timezone.utc).date()

    pairs, source = _select_universe(con, params)
    limit = params.get("limit")
    if limit:
        pairs = pairs[: int(limit)]

    done = _already_done(con, as_of)
    pending = [(tk, yft) for tk, yft in pairs if tk not in done]
    print(f"[earnings] as_of={as_of} universe={len(pairs)} source='{source}' "
          f"already_done_today={len(done & {tk for tk, _ in pairs})} pending={len(pending)}")

    inserted = 0
    with_date = 0   # names that returned at least one upcoming date
    no_date = 0     # fetched OK but no upcoming date (recently reported, ETF, etc.)
    failed = 0      # hard fetch failure (gap)
    buffer: list[dict] = []

    def _flush() -> None:
        nonlocal inserted, buffer
        if buffer:
            inserted += db.insert_earnings(con, pd.DataFrame(buffer), as_of=as_of)
            buffer = []

    for i, (canon, yft) in enumerate(pending, 1):
        cal = _fetch_calendar(yft)
        if cal is None:
            failed += 1
        else:
            parsed = _dates_from_calendar(cal)
            if parsed is None:
                no_date += 1
            else:
                dates, is_est = parsed
                with_date += 1
                for d in dates:
                    buffer.append({"ticker": canon, "earnings_date": d,
                                   "is_estimate": is_est})
        if i % FLUSH_EVERY == 0:
            _flush()
            print(f"[earnings] {i}/{len(pending)} pulled (with_date={with_date} "
                  f"no_date={no_date} failed={failed} inserted={inserted})")
        time.sleep(PER_NAME_SLEEP)
    _flush()

    store_gb = rsc.dir_size_gb(STORE_DIR)
    total_rows = con.execute(
        "SELECT COUNT(*) FROM earnings_calendar WHERE as_of = ?", [as_of]
    ).fetchone()[0]
    accounting = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "universe": len(pairs),
        "universe_source": source,
        "pulled_this_run": len(pending),
        "with_upcoming_date": with_date,
        "no_upcoming_date": no_date,
        "failed_tickers": failed,
        "rows_inserted_this_run": inserted,
        "rows_for_as_of": total_rows,
        "store_gb": round(store_gb, 2),
    }
    rsc.merge_meta(meta_path, {"earnings": accounting})
    rsc.update_disk_warning(meta_path, store_gb)

    print(f"[earnings] DONE as_of={as_of} pulled={len(pending)} with_date={with_date} "
          f"no_date={no_date} failed={failed} inserted={inserted} "
          f"rows_for_as_of={total_rows} store={store_gb:.2f}GiB")
    return accounting


# --------------------------------------------------------------------------- #
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Daily earnings-calendar miner (§12.2).")
    ap.add_argument("--db", default=None, help="DuckDB path (default: store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--tickers", default=None, help="comma list, e.g. AAPL,MSFT")
    ap.add_argument("--limit", type=int, default=None, help="cap to first N names")
    args = ap.parse_args()

    params: dict = {}
    if args.tickers:
        params["tickers"] = args.tickers
    if args.limit:
        params["limit"] = args.limit

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)
    db.init_mining_schema(con)
    run(params, con, meta_path=args.meta)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
