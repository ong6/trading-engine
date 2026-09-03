#!/usr/bin/env python
"""Weekly fundamentals snapshot miner (§12.2).

Free fundamentals (market cap, PE, EV/EBITDA-ish, sector, …) are point-in-time
truth that no vendor sells cheaply after the fact. Snapshotting them weekly and
*never rewriting a past row* builds the honest history that value strategies
need in ~6–12 months. This is a citizen of the §12.7 job queue: the queue
dispatches to `run(params, con, meta_path)`; a `__main__` here runs it standalone
for testing.

Universe: every liquid name (the same `universe.liquid = TRUE` set collect.py
uses). ETFs come along and simply store NULL for the equity-only fields — honest,
not fabricated.

Source: yfinance `Ticker.info` — one request per name (the API does NOT batch
`.info`), so this is inherently sequential. We take whatever fields are honestly
present and record NULL for the rest; a name that returns no quote at all
(quoteType is None) is counted as a gap, never stored as an empty row.

Guardrails: append-only + point-in-time (db.insert_fundamentals anti-joins on
(ticker, as_of) — a re-run on the same day inserts nothing), polite per-name
pulls (small sleep between names, one backoff retry then record a gap — never
loop on a blocked name), honest _meta.json accounting, resumable (skip names
already snapshotted for today's as_of).
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from engine.lib import db
from engine.lib import resources as rsc
from engine.lib.settings import STORE_DIR
from engine.lib.settings import META_PATH as DEFAULT_META

PER_NAME_SLEEP = 0.4       # politeness pause between per-name .info requests
RETRY_SLEEP = 15           # one backoff before recording a name as a gap
FLUSH_EVERY = 25           # insert + checkpoint progress every N names (resumability)

# yfinance .info key -> our column. Take what's honestly free; NULL the rest.
_INFO_MAP = {
    "marketCap": "market_cap",
    "trailingPE": "trailing_pe",
    "forwardPE": "forward_pe",
    "priceToBook": "price_to_book",
    "priceToSalesTrailing12Months": "price_to_sales",
    "enterpriseValue": "enterprise_value",
    "enterpriseToEbitda": "ev_to_ebitda",
    "enterpriseToRevenue": "ev_to_revenue",
    "ebitda": "ebitda",
    "trailingEps": "trailing_eps",
    "forwardEps": "forward_eps",
    "profitMargins": "profit_margins",
    "dividendYield": "dividend_yield",
    "beta": "beta",
    "sharesOutstanding": "shares_outstanding",
    "sector": "sector",
    "industry": "industry",
    "quoteType": "quote_type",
    "currency": "currency",
}


# --------------------------------------------------------------------------- #
# universe selection + resumability
# --------------------------------------------------------------------------- #
def _select_universe(con, params: dict) -> list[tuple[str, str]]:
    """(canonical, yf) pairs to snapshot. --tickers overrides; else all liquid
    names (collect.py's liquid set)."""
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
        # names not in the universe still get pulled (identity yf ticker)
        return [(tk, found.get(tk, tk)) for tk in tickers]

    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE liquid = TRUE ORDER BY ticker"
    ).fetchall()
    return [(tk, yft or tk) for tk, yft in rows]


def _already_done(con, as_of: date) -> set[str]:
    """Tickers already snapshotted for this as_of (the resume set)."""
    rows = con.execute(
        "SELECT DISTINCT ticker FROM fundamentals WHERE as_of = ?", [as_of]
    ).fetchall()
    return {r[0] for r in rows}


# --------------------------------------------------------------------------- #
# per-name fetch
# --------------------------------------------------------------------------- #
def _fetch_info(yf_ticker: str) -> dict | None:
    """One `.info` pull with a single backoff retry. Returns the dict, or None
    on hard failure (the caller records a gap — never loops)."""
    try:
        return yf.Ticker(yf_ticker).info
    except Exception:  # noqa: BLE001 - resilient, retry once
        time.sleep(RETRY_SLEEP)
        try:
            return yf.Ticker(yf_ticker).info
        except Exception:  # noqa: BLE001
            return None


def _row_from_info(canon: str, info: dict | None) -> dict | None:
    """Map a `.info` dict to our fundamentals row. Returns None when the pull
    carried no real quote (quoteType is None / empty dict) — that's a gap, not a
    row. Missing individual fields are simply absent (stored NULL downstream)."""
    if not info or info.get("quoteType") is None:
        return None
    row: dict = {"ticker": canon}
    for src, dst in _INFO_MAP.items():
        val = info.get(src)
        if val is not None:
            row[dst] = val
    return row


# --------------------------------------------------------------------------- #
# entry point the queue dispatches to
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """Snapshot fundamentals for the liquid universe into the append-only
    `fundamentals` table, stamped with today's as_of. Point-in-time: a re-run on
    the same day is a no-op (resumability skip + insert anti-join).

    params:
      tickers — 'A,B,C' or a list: snapshot only these (testing).
      limit   — cap to the first N names (fast smoke tests).
    Returns the accounting dict also written under _meta.json 'fundamentals'.
    """
    params = params or {}
    db.init_mining_schema(con)
    as_of = datetime.now(timezone.utc).date()

    pairs = _select_universe(con, params)
    limit = params.get("limit")
    if limit:
        pairs = pairs[: int(limit)]

    done = _already_done(con, as_of)
    pending = [(tk, yft) for tk, yft in pairs if tk not in done]
    print(f"[fundamentals] as_of={as_of} universe={len(pairs)} "
          f"already_done_today={len(done & {tk for tk, _ in pairs})} "
          f"pending={len(pending)}")

    inserted = 0
    with_data = 0
    failed = 0
    with_mcap = 0
    buffer: list[dict] = []

    def _flush() -> None:
        nonlocal inserted, buffer
        if buffer:
            inserted += db.insert_fundamentals(con, pd.DataFrame(buffer), as_of=as_of)
            buffer = []

    for i, (canon, yft) in enumerate(pending, 1):
        info = _fetch_info(yft)
        row = _row_from_info(canon, info)
        if row is None:
            failed += 1
        else:
            with_data += 1
            if row.get("market_cap") is not None:
                with_mcap += 1
            buffer.append(row)
        if i % FLUSH_EVERY == 0:
            _flush()
            print(f"[fundamentals] {i}/{len(pending)} pulled "
                  f"(with_data={with_data} failed={failed} inserted={inserted})")
        time.sleep(PER_NAME_SLEEP)
    _flush()

    store_gb = rsc.dir_size_gb(STORE_DIR)
    total_rows = con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE as_of = ?", [as_of]
    ).fetchone()[0]
    accounting = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "universe": len(pairs),
        "pulled_this_run": len(pending),
        "with_data": with_data,
        "with_market_cap": with_mcap,
        "failed_tickers": failed,
        "rows_inserted_this_run": inserted,
        "rows_for_as_of": total_rows,
        "store_gb": round(store_gb, 2),
    }
    rsc.merge_meta(meta_path, {"fundamentals": accounting})
    rsc.update_disk_warning(meta_path, store_gb)

    print(f"[fundamentals] DONE as_of={as_of} pulled={len(pending)} "
          f"with_data={with_data} with_mcap={with_mcap} failed={failed} "
          f"inserted={inserted} rows_for_as_of={total_rows} store={store_gb:.2f}GiB")
    return accounting


# --------------------------------------------------------------------------- #
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Weekly fundamentals snapshot miner (§12.2).")
    ap.add_argument("--db", default=None, help="DuckDB path (default: store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--tickers", default=None, help="comma list, e.g. AAPL,MSFT,SPY")
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
