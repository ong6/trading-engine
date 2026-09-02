#!/usr/bin/env python
"""Collect EOD bars from yfinance into DuckDB.

Four modes:
  --bootstrap-floor  fetch ~90d for every active name, then compute the
                     liquidity floor from our own stored prices.
  --backfill         fetch max history for liquid names not yet backfilled
                     (resumable via universe.backfill_done + jobs table).
  --refresh-liquid   WEEKLY: re-pull ~90d for active names currently NOT liquid,
                     recompute `universe.liquid` for everyone from the trailing
                     63-session median dollar volume (same floor as bootstrap),
                     admit newly qualifying names (+ their max-history backfill
                     via --backfill's path) and demote names that no longer
                     qualify — flag only, never a row. `--dry-run` reports.
  (default)          incremental daily pull of the last few sessions for liquid
                     names, gated on the NYSE trading calendar.

`liquid` is owned HERE (not universe.py): universe.py mirrors the Nasdaq symbol
directory — membership and `active` — and never looks at a price; the liquidity
floor is a statement about OUR stored bars, and both consumers of the flag
(--backfill, incremental) live in this file. Until 2026-09-02 the flag was
written exactly once, by --bootstrap-floor on 2026-07-16: 336 names added since
sat at liquid=FALSE forever and every universe_snapshot row repeated the 07-16
verdict — the forward record could never admit a newly liquid name (inverse
survivorship). --refresh-liquid is the fix.

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
from lib import resources as rsc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
META_PATH = REPO_ROOT / "data" / "_meta.json"

_YF_FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}

# The liquidity floor. ONE rule, used by --bootstrap-floor (2026-07-16),
# --refresh-liquid, and mirrored by farm/backtest/hist_screen.py's `prices`
# membership (LIQ_MIN_CLOSE / LIQ_MIN_MDV / LIQ_BARS there — keep in sync):
# last close >= $3 and median(close * volume) >= $5M over the trailing window.
# Bootstrap's window was "the ~90 calendar days we had", i.e. ~63 sessions;
# the refresh pins it to the last LIQ_BARS sessions present in `prices`.
LIQ_MIN_CLOSE = 3.0
LIQ_MIN_MDV = 5_000_000.0
LIQ_BARS = 63


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
    start = (datetime.now(timezone.utc).date() - timedelta(days=90)).isoformat()

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
          AND l.last_close >= ?
          AND l.med_dollar_vol >= ?
        """,
        [LIQ_MIN_CLOSE, LIQ_MIN_MDV],
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


# --------------------------------------------------------------------------- #
# liquidity refresh (weekly)
# --------------------------------------------------------------------------- #
def liquid_flags(con, as_of: date | None = None) -> pd.DataFrame:
    """Per-ticker liquidity verdict over the trailing LIQ_BARS sessions ending
    at `as_of` (default: MAX(date) in prices). Columns: ticker, last_close,
    med_dollar_vol, nbars, qualifies. Sessions are the distinct dates present in
    `prices`, so a name with no bars inside the window has no row here and
    therefore does not qualify — a name we stopped receiving bars for cannot
    stay liquid on the strength of old data."""
    if as_of is None:
        as_of = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if as_of is None:
        return pd.DataFrame(columns=["ticker", "last_close", "med_dollar_vol",
                                     "nbars", "qualifies"])
    days = con.execute(
        "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
        [as_of, LIQ_BARS],
    ).fetchall()
    window_start = days[-1][0]
    df = con.execute(
        """
        SELECT ticker,
               arg_max(close, date)   AS last_close,
               median(close * volume) AS med_dollar_vol,
               COUNT(*)               AS nbars
        FROM prices
        WHERE date >= ? AND date <= ?
        GROUP BY ticker
        ORDER BY ticker
        """,
        [window_start, as_of],
    ).fetch_df()
    df["qualifies"] = (df["last_close"] >= LIQ_MIN_CLOSE) & (df["med_dollar_vol"] >= LIQ_MIN_MDV)
    return df


def _held_tickers(con) -> set[str]:
    """Names any league book currently holds (empty if the sim schema is absent)."""
    has = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'sim_positions'"
    ).fetchone()[0]
    if not has:
        return set()
    return {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM sim_positions WHERE qty > 0").fetchall()}


def apply_liquid_flags(con, flags: pd.DataFrame, *, dry_run: bool) -> dict:
    """Reconcile universe.liquid with `flags`. Admits ACTIVE names that qualify;
    demotes liquid names that don't (active or not). Flag-only: no universe or
    price row is ever deleted, and universe_snapshot is untouched (universe.py
    appends the next snapshot from the refreshed flag, so the forward record
    starts moving). Names a league book HOLDS are never demoted: the incremental
    pull only fetches liquid names, so demoting a held name would freeze its
    mark — they are reported under `kept_held` instead."""
    qualifying = set(flags.loc[flags["qualifies"], "ticker"])
    rows = con.execute("SELECT ticker, active, liquid FROM universe").fetchall()
    held = _held_tickers(con)
    admit, demote, kept_held = [], [], []
    for tk, active, liquid in rows:
        if not liquid and active and tk in qualifying:
            admit.append(tk)
        elif liquid and tk not in qualifying:
            (kept_held if tk in held else demote).append(tk)
    admit.sort(); demote.sort(); kept_held.sort()
    if not dry_run:
        if admit:
            con.executemany("UPDATE universe SET liquid = TRUE WHERE ticker = ?",
                            [[t] for t in admit])
        if demote:
            con.executemany("UPDATE universe SET liquid = FALSE WHERE ticker = ?",
                            [[t] for t in demote])
    liquid_after = con.execute("SELECT COUNT(*) FROM universe WHERE liquid = TRUE").fetchone()[0]
    return {"admitted": admit, "demoted": demote, "kept_held": kept_held,
            "liquid_after": int(liquid_after), "dry_run": dry_run}


def mode_refresh_liquid(con, limit: int | None, dry_run: bool) -> tuple[int, int, dict]:
    """Weekly liquidity refresh. Returns (requested, failed, summary).

    1. ~90d pull for ACTIVE names that are NOT liquid today (liquid names are
       already current from the nightly incremental; non-liquid names have had
       no bars since bootstrap, so without this step they could never qualify).
       Real bars are upserted even under --dry-run — they are market data, not
       a decision.
    2. Recompute the flag for everyone (liquid_flags) and reconcile
       (apply_liquid_flags).
    3. Newly admitted names carry backfill_done = FALSE, so the existing
       --backfill path fetches their max history — the same resumable job the
       bootstrap used. Skipped under --dry-run.
    """
    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE active = TRUE AND liquid = FALSE "
        "ORDER BY ticker" + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    yf_to_canon = {yft: tk for tk, yft in rows}
    all_yf = list(yf_to_canon)
    start = (datetime.now(timezone.utc).date() - timedelta(days=90)).isoformat()
    got_all: set[str] = set()
    for i, batch in enumerate(_batches(all_yf, 200), 1):
        sub_map = {y: yf_to_canon[y] for y in batch}
        raw = _download(batch, period=None, start=start)
        df, got = _extract_long(raw, sub_map)
        n = db.upsert_prices(con, df)
        got_all |= got
        print(f"[refresh-liquid] candidates batch {i} ({len(batch)} tickers) -> {n} rows ({len(got)} with data)")
        time.sleep(2)
    failed = len(all_yf) - len(got_all)

    flags = liquid_flags(con)
    summary = apply_liquid_flags(con, flags, dry_run=dry_run)
    summary.update({
        "as_of": str(con.execute("SELECT MAX(date) FROM prices").fetchone()[0]),
        "candidates_pulled": len(all_yf), "candidates_failed": failed,
        "rule": f"last_close >= {LIQ_MIN_CLOSE:g} AND median(close*volume) >= "
                f"{LIQ_MIN_MDV:g} over trailing {LIQ_BARS} sessions",
    })
    tag = "DRY-RUN would" if dry_run else "did"
    print(f"[refresh-liquid] {tag} admit={len(summary['admitted'])} "
          f"demote={len(summary['demoted'])} kept_held={len(summary['kept_held'])} "
          f"liquid_after={summary['liquid_after']} (as_of {summary['as_of']})")
    for key in ("admitted", "demoted", "kept_held"):
        if summary[key]:
            print(f"[refresh-liquid]   {key}: {' '.join(summary[key])}")

    if not dry_run and summary["admitted"]:
        print(f"[refresh-liquid] backfilling {len(summary['admitted'])} admitted names (max history)")
        bf_total, bf_failed = mode_backfill(con, None)
        summary["backfill"] = {"processed": bf_total, "failed": bf_failed}
    return len(all_yf), failed, summary


def _is_trading_day(day: date) -> bool:
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=day.isoformat(), end_date=day.isoformat())
    return not sched.empty


def mode_incremental(con, force: bool) -> tuple[int, int]:
    """Daily pull of the last few sessions for liquid names. Calendar-gated."""
    today = datetime.now(timezone.utc).date()
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

    today = datetime.now(timezone.utc).date()
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

    # Keyed on the last bar that actually TRADED (db.REAL_BAR_SQL), the rule
    # league.md uses for stale marks — yfinance keeps emitting zero-volume dead
    # quotes after a name stops trading, and MAX(date) counted them as fresh.
    cutoff = _stale_cutoff(3)
    stale = con.execute(
        f"""
        SELECT u.ticker
        FROM universe u
        LEFT JOIN (SELECT ticker, MAX(date) FILTER (WHERE {db.REAL_BAR_SQL}) md
                   FROM prices GROUP BY ticker) p
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
    rsc.write_text_atomic(META_PATH, json.dumps(meta, indent=2))
    print(f"[meta] wrote {META_PATH} (prices_rows={prices_rows}, liquid={liquid_count}, stale={len(stale_list)})")


def update_meta(**updates) -> None:
    """Read-modify-write _meta.json (screen.py's shape) — for the weekly refresh,
    which must not clobber the nightly's regime/screen keys the way write_meta
    (the nightly's FIRST writer) legitimately does."""
    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
        except json.JSONDecodeError:
            meta = {}
    meta.update(updates)
    rsc.write_text_atomic(META_PATH, json.dumps(meta, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect EOD bars from yfinance into DuckDB.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bootstrap-floor", action="store_true", help="90d pull + liquidity floor")
    g.add_argument("--backfill", action="store_true", help="max-history backfill of liquid names")
    g.add_argument("--refresh-liquid", action="store_true",
                   help="weekly: recompute universe.liquid from the trailing 63-session "
                        "median dollar volume, admit + backfill new names, demote (flag only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --refresh-liquid: report admit/demote, write no flags, "
                         "no backfill, no _meta.json (the ~90d candidate pull still lands)")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB path (default: the store)")
    ap.add_argument("--limit", type=int, default=None, help="process only first N names (smoke tests)")
    ap.add_argument("--force", action="store_true", help="run incremental even on a non-trading day")
    args = ap.parse_args()

    con = db.connect(args.db)
    db.init_schema(con)

    if args.bootstrap_floor:
        mode = "bootstrap-floor"
        requested, failed = mode_bootstrap_floor(con, args.limit)
    elif args.backfill:
        mode = "backfill"
        requested, failed = mode_backfill(con, args.limit)
    elif args.refresh_liquid:
        requested, failed, summary = mode_refresh_liquid(con, args.limit, args.dry_run)
        con.close()
        if not args.dry_run:
            summary["last_run"] = datetime.now(timezone.utc).isoformat()
            update_meta(liquid_refresh=summary)
            print(f"[meta] updated liquid_refresh in {META_PATH}")
        return 0
    else:
        mode = "incremental"
        requested, failed = mode_incremental(con, args.force)

    write_meta(con, mode, requested, failed)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
