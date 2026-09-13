#!/usr/bin/env python
"""Daily earnings-calendar miner (§12.2).

Upcoming earnings dates feed two things: the earnings-risk gate (don't hold a
swing into a print) and event studies later. Dates move as the quarter
approaches, so every pull is its own `as_of`-stamped snapshot and a gate lookup
uses the LATEST snapshot per ticker. A citizen of the §12.7 job queue: the queue
dispatches to `run(params, con, meta_path)`; a `__main__` here runs it standalone.

Universe (v1 boundary — see BUILDLOG): active non-ETF names with fundamentals
coverage (a `fundamentals` row whose market_cap is non-NULL) UNION the latest
screen's passers. Eligibility is enforced against the authoritative `universe`
row after that union, excluding ETFs (no earnings), inactive names, and stale
source rows while preserving each canonical name's Yahoo mapping. Fallback when
the `fundamentals` table is empty (fresh store, fundamentals not run yet): all
active, liquid, non-ETF names. Explicit `tickers` remain an unrestricted operator
override. The selected source is reported in _meta.json under `universe_source`.

Source: yfinance `Ticker.calendar['Earnings Date']` — one request per name (no
batch API). Returns a list of one date (single/confirmed) or two (an estimate
window); we store each date with is_estimate = (len != 1). Never fabricate a
date: a name that returns no calendar / no date is counted, not stored.

Guardrails: append-only (db.insert_earnings anti-joins on
(ticker, earnings_date, as_of) — a re-run on the same day inserts nothing), polite
per-name pulls (small sleep, one backoff retry then record a gap), honest
_meta.json accounting, and explicit per-attempt resume records. Successful pulls
with or without dates are skipped for today's as_of; failed pulls remain retryable.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import yfinance as yf

from engine.lib import db
from engine.lib import resources as rsc
from engine.lib.log import get_logger
from engine.lib.settings import META_PATH as DEFAULT_META
from engine.lib.settings import STORE_DIR
from engine.lib.util import table_exists

log = get_logger("earnings")

PER_NAME_SLEEP = 0.4       # politeness pause between per-name .calendar requests
RETRY_SLEEP = 15           # one backoff before recording a name as a gap
FLUSH_EVERY = 25           # insert + checkpoint progress every N names (resumability)


# --------------------------------------------------------------------------- #
# universe selection + resumability
# --------------------------------------------------------------------------- #
def _select_universe(con, params: dict) -> tuple[list[tuple[str, str]], str]:
    """Return ((canonical, yf) pairs, universe_source label). --tickers overrides;
    else active equities with fundamentals ∪ latest screen passers, falling back
    to active liquid non-ETF names when the fundamentals table is empty."""
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

    have_fund = table_exists(con, "fundamentals") and con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE market_cap IS NOT NULL"
    ).fetchone()[0] > 0
    if have_fund:
        # Equities the fundamentals miner has seen. Take the UNION of tickers with
        # a real market_cap across EVERY as_of in the trailing 14 days of MAX(as_of)
        # — not just MAX(as_of) alone. A single latest as_of can be a PARTIAL /
        # interrupted snapshot (miner mid-run), which would silently shrink the
        # earnings universe to only the names pulled so far. Unioning the recent
        # window means a partial snapshot only ever ADDS names, never drops coverage.
        rows = con.execute(
            """
            WITH latest AS (SELECT MAX(as_of) m FROM fundamentals)
            SELECT DISTINCT ticker FROM fundamentals
            WHERE market_cap IS NOT NULL
              AND as_of >= (SELECT m FROM latest) - INTERVAL 14 DAY
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
        "SELECT ticker, yf_ticker FROM universe "
        "WHERE active = TRUE AND etf = FALSE AND ticker IN "
        f"({','.join(['?'] * len(canon))})",
        list(canon),
    ).fetchall()
    return sorted((tk, yft or tk) for tk, yft in yf_rows), source


def _already_done(con, as_of: date) -> set[str]:
    """Tickers successfully pulled for this as_of (the resume set).

    `ok` and `empty` fetch-log rows are complete; `failed` rows remain retryable.
    Calendar rows are included for compatibility with snapshots created before
    the fetch log existed.
    """
    rows = con.execute(
        """
        SELECT ticker FROM earnings_calendar WHERE as_of = ?
        UNION
        SELECT ticker FROM earnings_fetch_log
        WHERE as_of = ? AND status IN ('ok', 'empty')
        """,
        [as_of, as_of],
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


def _dates_from_calendar(cal: dict | None, yf_ticker: str = "") -> tuple[list[date], bool] | None:
    """Extract upcoming earnings dates. Returns (dates, is_estimate) or None when
    there is no usable date. is_estimate = the source gave a window (len != 1),
    computed from the CLEANED list only.

    Every candidate is coerced through pd.to_datetime(errors="coerce"), so
    datetime, date, pandas Timestamp (incl. tz-aware → wall-clock .date()),
    numpy.datetime64 and ISO date strings are all handled. NaT / NaN / None
    window-fillers are dropped BEFORE the length test (so a [real_date, NaT]
    calendar stores a single confirmed date, not a mislabeled estimate); values
    that survive filtering but still fail to parse are dropped AND logged."""
    if not cal or not isinstance(cal, dict):
        return None
    raw = cal.get("Earnings Date")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    if len(raw) == 0:
        return None
    dates: list[date] = []
    for d in raw:
        # NaT / NaN / None: expected window-filler — drop silently (finding A).
        if pd.isna(d):
            continue
        ts = pd.to_datetime(d, errors="coerce")
        if pd.isna(ts):
            # A non-null value we could not parse (finding B) — never fabricate.
            log.warning(f"[earnings] dropped unparseable earnings-date value {d!r}"
                  + (f" for {yf_ticker}" if yf_ticker else ""))
            continue
        dates.append(ts.date())
    if not dates:
        return None
    return dates, len(dates) != 1


def _prepare_run(con, params: dict, as_of: date):
    pairs, source = _select_universe(con, params)
    limit = params.get("limit")
    if limit:
        pairs = pairs[: int(limit)]
    done = _already_done(con, as_of)
    pending = [(tk, yft) for tk, yft in pairs if tk not in done]
    already_done = len(done & {tk for tk, _ in pairs})
    return pairs, source, pending, already_done


def _write_checkpoint(con, calendar_rows: list[dict], fetch_rows: list[dict], as_of: date) -> int:
    """Commit calendar rows and their fetch outcomes as one recovery unit."""
    if not calendar_rows and not fetch_rows:
        return 0
    with db.transaction(con):
        inserted = db.insert_earnings(con, pd.DataFrame(calendar_rows), as_of=as_of)
        db.insert_earnings_fetch_log(con, fetch_rows, as_of=as_of)
    return inserted


def _pull_pending(
    pairs: list[tuple[str, str]],
    source: str,
    pending: list[tuple[str, str]],
    already_done: int,
    as_of: date,
    checkpoint: Callable[[list[dict], list[dict]], int],
    count_rows: Callable[[], int],
    meta_path: str | Path,
) -> dict:
    """Network loop shared by persistent and connection-narrowed entry points."""
    log.info(f"[earnings] as_of={as_of} universe={len(pairs)} source='{source}' "
          f"already_done_today={already_done} pending={len(pending)}")

    inserted = 0
    with_date = 0   # names that returned at least one upcoming date
    no_date = 0     # fetched OK but no upcoming date (recently reported, ETF, etc.)
    failed = 0      # hard fetch failure (gap)
    buffer: list[dict] = []
    fetch_log_buffer: list[dict] = []

    def _flush() -> None:
        nonlocal inserted, buffer, fetch_log_buffer
        if not buffer and not fetch_log_buffer:
            return
        inserted += checkpoint(buffer, fetch_log_buffer)
        buffer = []
        fetch_log_buffer = []

    for i, (canon, yft) in enumerate(pending, 1):
        cal = _fetch_calendar(yft)
        if cal is None:
            failed += 1
            fetch_log_buffer.append({"ticker": canon, "status": "failed", "n_dates": 0})
        else:
            parsed = _dates_from_calendar(cal, yft)
            if parsed is None:
                no_date += 1
                fetch_log_buffer.append({"ticker": canon, "status": "empty", "n_dates": 0})
            else:
                dates, is_est = parsed
                with_date += 1
                fetch_log_buffer.append(
                    {"ticker": canon, "status": "ok", "n_dates": len(dates)}
                )
                for d in dates:
                    buffer.append({"ticker": canon, "earnings_date": d,
                                   "is_estimate": is_est})
        if i % FLUSH_EVERY == 0:
            _flush()
            log.info(f"[earnings] {i}/{len(pending)} pulled (with_date={with_date} "
                  f"no_date={no_date} failed={failed} inserted={inserted})")
        time.sleep(PER_NAME_SLEEP)
    _flush()

    store_gb = rsc.dir_size_gb(STORE_DIR)
    total_rows = count_rows()
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

    log.info(f"[earnings] DONE as_of={as_of} pulled={len(pending)} with_date={with_date} "
          f"no_date={no_date} failed={failed} inserted={inserted} "
          f"rows_for_as_of={total_rows} store={store_gb:.2f}GiB")
    return accounting


# --------------------------------------------------------------------------- #
# entry point the queue dispatches to
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """Pull upcoming earnings dates for the earnings universe into the
    append-only `earnings_calendar` table, stamped with today's as_of. Every
    attempt is also appended to `earnings_fetch_log`; a re-run skips successful
    `ok`/`empty` pulls and retries failures.

    params:
      tickers — 'A,B,C' or a list: pull only these (testing).
      limit   — cap to the first N names (fast smoke tests).
    Returns the accounting dict also written under _meta.json 'earnings'.
    """
    params = params or {}
    db.init_mining_schema(con)
    as_of = datetime.now(timezone.utc).date()
    pairs, source, pending, already_done = _prepare_run(con, params, as_of)
    return _pull_pending(
        pairs,
        source,
        pending,
        already_done,
        as_of,
        lambda calendar_rows, fetch_rows: _write_checkpoint(
            con, calendar_rows, fetch_rows, as_of
        ),
        lambda: con.execute(
            "SELECT COUNT(*) FROM earnings_calendar WHERE as_of = ?", [as_of]
        ).fetchone()[0],
        meta_path,
    )


def run_connection_narrowed(
    params: dict | None,
    db_path: str | Path | None = None,
    meta_path: str | Path = DEFAULT_META,
) -> dict:
    """Run without retaining DuckDB's writer lock during per-name HTTP waits.

    The queue owns process-level serialization. This entry point leases the DB
    briefly for setup, each 25-name transactional checkpoint, and final
    accounting, allowing API/UI readers between those bounded writes.
    """
    params = params or {}
    path = Path(db_path) if db_path is not None else db.DEFAULT_DB
    as_of = datetime.now(timezone.utc).date()
    con = db.connect(path)
    try:
        db.init_schema(con)
        db.init_queue_schema(con)
        db.init_mining_schema(con)
        prepared = _prepare_run(con, params, as_of)
    finally:
        con.close()

    def checkpoint(calendar_rows: list[dict], fetch_rows: list[dict]) -> int:
        write_con = db.connect(path)
        try:
            return _write_checkpoint(write_con, calendar_rows, fetch_rows, as_of)
        finally:
            write_con.close()

    def count_rows() -> int:
        read_con = db.connect(path, read_only=True)
        try:
            return read_con.execute(
                "SELECT COUNT(*) FROM earnings_calendar WHERE as_of = ?", [as_of]
            ).fetchone()[0]
        finally:
            read_con.close()

    return _pull_pending(*prepared, as_of, checkpoint, count_rows, meta_path)


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

    run_connection_narrowed(params, db_path=args.db, meta_path=args.meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
