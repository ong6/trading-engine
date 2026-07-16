#!/usr/bin/env python
"""Collect EOD bars from yfinance into DuckDB.

Three modes:
  --bootstrap-floor  fetch ~90d for every active name, then compute the
                     liquidity floor from our own stored prices.
  --backfill         fetch max history for liquid names not yet backfilled
                     (resumable via universe.backfill_done + jobs table).
  (default)          incremental daily pull of the last few sessions for liquid
                     names, gated on the NYSE trading calendar.

Guardrails: never fabricate a bar (NaN closes are dropped upstream), polite
pulls (batched, sleeps, one backoff retry), only yfinance + nasdaqtrader.com.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
META_PATH = REPO_ROOT / "data" / "_meta.json"

_YF_FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


# --------------------------------------------------------------------------- #
# yfinance download + parsing
# --------------------------------------------------------------------------- #
def _frame_from_sub(sub: pd.DataFrame, canon: str) -> pd.DataFrame | None:
    """Turn a single ticker's OHLCV sub-frame into our long schema."""
    sub = sub.reset_index()
    sub = sub.rename(columns={sub.columns[0]: "date"})
    if any(f not in sub.columns for f in _YF_FIELDS):
        return None
    out = sub[["date", "Open", "High", "Low", "Close", "Volume"]].rename(columns=_YF_FIELDS)
    out["ticker"] = canon
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out = out.dropna(subset=["close"])
    if out.empty:
        return None
    return out[["ticker", "date", "open", "high", "low", "close", "volume"]]


def _extract_long(raw: pd.DataFrame, yf_to_canon: dict[str, str]) -> tuple[pd.DataFrame, set[str]]:
    """Flatten a yf.download result into long form. Returns (df, set of yf
    tickers that actually produced usable rows)."""
    if raw is None or raw.empty:
        return pd.DataFrame(), set()

    frames: list[pd.DataFrame] = []
    got: set[str] = set()

    if isinstance(raw.columns, pd.MultiIndex):
        available = set(raw.columns.get_level_values(0))
        for yft, canon in yf_to_canon.items():
            if yft not in available:
                continue
            f = _frame_from_sub(raw[yft], canon)
            if f is not None:
                frames.append(f)
                got.add(yft)
    elif len(yf_to_canon) == 1:
        (yft, canon), = yf_to_canon.items()
        f = _frame_from_sub(raw, canon)
        if f is not None:
            frames.append(f)
            got.add(yft)

    if not frames:
        return pd.DataFrame(), got
    return pd.concat(frames, ignore_index=True), got


def _download(yf_tickers: list[str], *, period: str | None, start: str | None,
              retry_sleep: int = 30) -> pd.DataFrame:
    """One yf.download call with a single backoff retry on exception."""
    kwargs = dict(group_by="ticker", auto_adjust=False, threads=True, progress=False)
    if period:
        kwargs["period"] = period
    if start:
        kwargs["start"] = start
    try:
        return yf.download(yf_tickers, **kwargs)
    except Exception as exc:  # noqa: BLE001 - be resilient, retry once
        print(f"[collect] batch download failed ({exc}); retry in {retry_sleep}s")
        time.sleep(retry_sleep)
        try:
            return yf.download(yf_tickers, **kwargs)
        except Exception as exc2:  # noqa: BLE001
            print(f"[collect] batch retry failed ({exc2}); marking batch failed")
            return pd.DataFrame()


def _batches(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# --------------------------------------------------------------------------- #
# jobs bookkeeping (backfill resumability)
# --------------------------------------------------------------------------- #
def _start_job(con, kind: str, params: str, total: int) -> int:
    nid = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM jobs").fetchone()[0]
    now = datetime.now(timezone.utc)
    con.execute(
        "INSERT INTO jobs (id, kind, params, state, progress, created_at, updated_at) "
        "VALUES (?, ?, ?, 'running', ?, ?, ?)",
        [nid, kind, params, f"0/{total}", now, now],
    )
    return nid


def _update_job(con, jid: int, progress: str, state: str = "running") -> None:
    con.execute(
        "UPDATE jobs SET progress = ?, state = ?, updated_at = ? WHERE id = ?",
        [progress, state, datetime.now(timezone.utc), jid],
    )


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #
def mode_bootstrap_floor(con, limit: int | None) -> tuple[int, int]:
    """Fetch ~90d for active names, then set universe.liquid from our own data.
    Returns (requested, failed)."""
    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE active = TRUE ORDER BY ticker"
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    yf_to_canon = {yft: tk for tk, yft in rows}
    all_yf = list(yf_to_canon)
    start = (date.today() - timedelta(days=90)).isoformat()

    got_all: set[str] = set()
    for batch in _batches(all_yf, 200):
        sub_map = {y: yf_to_canon[y] for y in batch}
        raw = _download(batch, period=None, start=start)
        df, got = _extract_long(raw, sub_map)
        n = db.upsert_prices(con, df)
        got_all |= got
        print(f"[bootstrap] batch {len(batch)} tickers -> {n} rows ({len(got)} with data)")
        time.sleep(2)

    # Liquidity floor computed from OUR stored prices, over the window we have.
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _liq AS
        SELECT ticker,
               arg_max(close, date)    AS last_close,
               median(close * volume)  AS med_dollar_vol
        FROM prices GROUP BY ticker
        """
    )
    con.execute("UPDATE universe SET liquid = FALSE")
    con.execute(
        """
        UPDATE universe u SET liquid = TRUE
        FROM _liq l
        WHERE u.ticker = l.ticker
          AND l.last_close >= 3
          AND l.med_dollar_vol >= 5000000
        """
    )

    active = con.execute("SELECT COUNT(*) FROM universe WHERE active = TRUE").fetchone()[0]
    priced = con.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
    liquid = con.execute("SELECT COUNT(*) FROM universe WHERE liquid = TRUE").fetchone()[0]
    failed = len(all_yf) - len(got_all)
    print(f"[bootstrap] active={active} priced={priced} liquid={liquid} failed={failed}")
    return len(all_yf), failed


def mode_backfill(con, limit: int | None) -> tuple[int, int]:
    """Max-history backfill for liquid, not-yet-done names. Resumable: the
    WHERE backfill_done = FALSE query IS the resume mechanism."""
    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe "
        "WHERE liquid = TRUE AND backfill_done = FALSE ORDER BY ticker"
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    yf_to_canon = {yft: tk for tk, yft in rows}
    all_yf = list(yf_to_canon)
    total = len(all_yf)
    if total == 0:
        print("[backfill] nothing pending")
        return 0, 0

    jid = _start_job(con, "backfill", f"limit={limit}", total)
    n_done = 0
    got_all: set[str] = set()

    for batch in _batches(all_yf, 50):
        sub_map = {y: yf_to_canon[y] for y in batch}
        raw = _download(batch, period="max", start=None)
        df, got = _extract_long(raw, sub_map)
        n = db.upsert_prices(con, df)
        got_all |= got
        if got:
            done_canon = [sub_map[y] for y in got]
            con.executemany(
                "UPDATE universe SET backfill_done = TRUE WHERE ticker = ?",
                [[c] for c in done_canon],
            )
        n_done += len(batch)
        _update_job(con, jid, f"{n_done}/{total}")
        print(f"[backfill] batch {len(batch)} -> {n} rows ({len(got)} done); progress {n_done}/{total}")
        time.sleep(2)

    _update_job(con, jid, f"{n_done}/{total}", state="done")
    failed = total - len(got_all)
    print(f"[backfill] processed={total} with_data={len(got_all)} failed={failed}")
    return total, failed


def _is_trading_day(day: date) -> bool:
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=day.isoformat(), end_date=day.isoformat())
    return not sched.empty


def mode_incremental(con, force: bool) -> tuple[int, int]:
    """Daily pull of the last few sessions for liquid names. Calendar-gated."""
    today = date.today()
    if not force and not _is_trading_day(today):
        print(f"[incremental] {today} is not an NYSE trading day; skipping (use --force to override)")
        return 0, 0

    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE liquid = TRUE ORDER BY ticker"
    ).fetchall()
    yf_to_canon = {yft: tk for tk, yft in rows}
    all_yf = list(yf_to_canon)

    got_all: set[str] = set()
    for batch in _batches(all_yf, 200):
        sub_map = {y: yf_to_canon[y] for y in batch}
        raw = _download(batch, period="5d", start=None)
        df, got = _extract_long(raw, sub_map)
        n = db.upsert_prices(con, df)
        got_all |= got
        print(f"[incremental] batch {len(batch)} -> {n} rows ({len(got)} with data)")
        time.sleep(2)

    failed = len(all_yf) - len(got_all)
    print(f"[incremental] liquid={len(all_yf)} with_data={len(got_all)} failed={failed}")
    return len(all_yf), failed


# --------------------------------------------------------------------------- #
# health metadata
# --------------------------------------------------------------------------- #
def _stale_cutoff(n: int = 3) -> date:
    """Date such that a latest bar older than it is >n trading days stale."""
    import pandas_market_calendars as mcal

    today = date.today()
    nyse = mcal.get_calendar("NYSE")
    days = [d.date() for d in nyse.valid_days(
        start_date=(today - timedelta(days=40)).isoformat(), end_date=today.isoformat())]
    days = [d for d in days if d <= today]
    if len(days) > n:
        return days[-(n + 1)]
    return days[0] if days else today


def write_meta(con, mode: str, requested: int, failed: int) -> None:
    universe_size = con.execute("SELECT COUNT(*) FROM universe").fetchone()[0]
    active_count = con.execute("SELECT COUNT(*) FROM universe WHERE active = TRUE").fetchone()[0]
    liquid_count = con.execute("SELECT COUNT(*) FROM universe WHERE liquid = TRUE").fetchone()[0]
    prices_rows = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    tickers_with_data = con.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]

    cutoff = _stale_cutoff(3)
    stale = con.execute(
        """
        SELECT u.ticker
        FROM universe u
        LEFT JOIN (SELECT ticker, MAX(date) md FROM prices GROUP BY ticker) p
               ON u.ticker = p.ticker
        WHERE u.liquid = TRUE AND (p.md IS NULL OR p.md < ?)
        ORDER BY u.ticker
        """,
        [cutoff],
    ).fetchall()
    stale_list = [r[0] for r in stale]

    degraded = requested > 0 and (failed / requested) > 0.10
    meta = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "universe_size": universe_size,
        "active_count": active_count,
        "liquid_count": liquid_count,
        "prices_rows": prices_rows,
        "tickers_with_data": tickers_with_data,
        "stale_tickers": {"count": len(stale_list), "list": stale_list[:50]},
        "failed_this_run": failed,
        "sources": {"stooq": "blocked", "yfinance": "degraded" if degraded else "ok"},
        "regime": None,
    }
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"[meta] wrote {META_PATH} (prices_rows={prices_rows}, liquid={liquid_count}, stale={len(stale_list)})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect EOD bars from yfinance into DuckDB.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bootstrap-floor", action="store_true", help="90d pull + liquidity floor")
    g.add_argument("--backfill", action="store_true", help="max-history backfill of liquid names")
    ap.add_argument("--limit", type=int, default=None, help="process only first N names (smoke tests)")
    ap.add_argument("--force", action="store_true", help="run incremental even on a non-trading day")
    args = ap.parse_args()

    con = db.connect()
    db.init_schema(con)

    if args.bootstrap_floor:
        mode = "bootstrap-floor"
        requested, failed = mode_bootstrap_floor(con, args.limit)
    elif args.backfill:
        mode = "backfill"
        requested, failed = mode_backfill(con, args.limit)
    else:
        mode = "incremental"
        requested, failed = mode_incremental(con, args.force)

    write_meta(con, mode, requested, failed)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
