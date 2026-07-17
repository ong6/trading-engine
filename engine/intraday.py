#!/usr/bin/env python
"""Intraday archiver (§12.2) — capture the free 1m/5m window before it expires.

Free sources only expose ~7 days of 1-minute and ~60 days of 5-minute bars.
Pulling daily and archiving forever compounds into a proprietary intraday
dataset. This job is the first citizen of the §12.7 job queue: the queue
dispatches to `run(params, con, meta_path)`; a `__main__` here enqueues+runs it
for convenience.

Universe for the pull:
  top 500 by 20-day median dollar volume (close*volume, from our own `prices`)
  UNION the latest screen's passers (screen_results, max run_date)
  UNION {SPY, QQQ, IWM}.

Guardrails: append-only (never update/overwrite a captured bar — see
db.insert_intraday), polite batched pulls (batch ~50, sleep between, one retry
then record a gap — never loop), UTC timestamps, honest _meta.json accounting.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db  # noqa: E402
from lib import resources as rsc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_META = REPO_ROOT / "data" / "_meta.json"
STORE_DIR = REPO_ROOT / "store"

BENCHMARKS = ["SPY", "QQQ", "IWM"]
BATCH_SIZE = 50
BATCH_SLEEP = 1.5          # politeness pause between batches
RETRY_SLEEP = 20           # one backoff before recording a batch as a gap

# yfinance intraday intervals -> pull window (free-tier limits)
INTERVALS = {"1m": "7d", "5m": "60d"}

_YF_FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


# --------------------------------------------------------------------------- #
# universe selection
# --------------------------------------------------------------------------- #
def _select_universe(con) -> list[str]:
    """Canonical tickers to archive: liquidity top-500 ∪ latest passers ∪ ETFs."""
    top = con.execute(
        """
        WITH recent AS (
            SELECT ticker, close, volume,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices
        )
        SELECT ticker
        FROM recent
        WHERE rn <= 20
        GROUP BY ticker
        HAVING COUNT(*) >= 5
        ORDER BY median(close * volume) DESC
        LIMIT 500
        """
    ).fetchall()
    tickers = {r[0] for r in top}

    # latest screen passers (guard: screen_results may be empty on a fresh DB)
    max_run = con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
    if max_run is not None:
        passers = con.execute(
            "SELECT ticker FROM screen_results "
            "WHERE run_date = ? AND passes_template = TRUE",
            [max_run],
        ).fetchall()
        tickers |= {r[0] for r in passers}

    tickers |= set(BENCHMARKS)
    return sorted(tickers)


def _yf_map(con, canon_tickers: list[str]) -> dict[str, str]:
    """Map canonical ticker -> yfinance ticker (fallback: the ticker itself)."""
    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE ticker IN "
        f"({','.join(['?'] * len(canon_tickers))})",
        canon_tickers,
    ).fetchall() if canon_tickers else []
    mapping = {tk: (yft or tk) for tk, yft in rows}
    # benchmarks / anything not in universe -> identity
    for tk in canon_tickers:
        mapping.setdefault(tk, tk)
    return mapping


def _batches(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# --------------------------------------------------------------------------- #
# yfinance intraday download + parsing
# --------------------------------------------------------------------------- #
def _to_utc(series: pd.Series) -> pd.Series:
    """Coerce a datetime column to tz-naive UTC. yfinance intraday indexes are
    tz-aware (usually US/Eastern); EOD-style naive input is assumed already UTC."""
    dt = pd.to_datetime(series)
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    return dt


def _frame_from_sub(sub: pd.DataFrame, canon: str, interval: str) -> pd.DataFrame | None:
    """Turn one ticker's intraday OHLCV sub-frame into our long schema."""
    sub = sub.reset_index()
    sub = sub.rename(columns={sub.columns[0]: "ts"})
    if any(f not in sub.columns for f in _YF_FIELDS):
        return None
    out = sub[["ts", "Open", "High", "Low", "Close", "Volume"]].rename(columns=_YF_FIELDS)
    out["ticker"] = canon
    out["interval"] = interval
    out["ts"] = _to_utc(out["ts"])
    out = out.dropna(subset=["close"])
    if out.empty:
        return None
    return out[["ticker", "ts", "interval", "open", "high", "low", "close", "volume"]]


def _extract_long(raw: pd.DataFrame, yf_to_canon: dict[str, str], interval: str
                  ) -> tuple[pd.DataFrame, set[str]]:
    """Flatten a yf.download intraday result to long form. Returns (df, set of
    yf tickers that produced usable rows)."""
    if raw is None or raw.empty:
        return pd.DataFrame(), set()

    frames: list[pd.DataFrame] = []
    got: set[str] = set()

    if isinstance(raw.columns, pd.MultiIndex):
        available = set(raw.columns.get_level_values(0))
        for yft, canon in yf_to_canon.items():
            if yft not in available:
                continue
            f = _frame_from_sub(raw[yft], canon, interval)
            if f is not None:
                frames.append(f)
                got.add(yft)
    elif len(yf_to_canon) == 1:
        (yft, canon), = yf_to_canon.items()
        f = _frame_from_sub(raw, canon, interval)
        if f is not None:
            frames.append(f)
            got.add(yft)

    if not frames:
        return pd.DataFrame(), got
    return pd.concat(frames, ignore_index=True), got


def _download(yf_tickers: list[str], *, interval: str, period: str) -> pd.DataFrame:
    """One yf.download intraday call with a single backoff retry on exception.
    An empty frame is returned on double-failure — the caller records the gap."""
    kwargs = dict(interval=interval, period=period, group_by="ticker",
                  auto_adjust=False, threads=True, progress=False)
    try:
        return yf.download(yf_tickers, **kwargs)
    except Exception as exc:  # noqa: BLE001 - be resilient, retry once
        print(f"[intraday] {interval} batch failed ({exc}); retry in {RETRY_SLEEP}s")
        time.sleep(RETRY_SLEEP)
        try:
            return yf.download(yf_tickers, **kwargs)
        except Exception as exc2:  # noqa: BLE001
            print(f"[intraday] {interval} batch retry failed ({exc2}); recording gap")
            return pd.DataFrame()


# --------------------------------------------------------------------------- #
# entry point the queue dispatches to
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """Pull 1m (7d) + 5m (60d) bars for the archive universe and append the new
    ones. Idempotent: re-running the same day inserts nothing new.

    params:
      limit — cap the universe to the first N tickers (for fast smoke tests;
              the full-500 run belongs to the main loop).
    Returns the accounting dict also written under the _meta.json 'intraday' key.
    """
    params = params or {}
    universe = _select_universe(con)
    print(f"[intraday] archive universe: {len(universe)} tickers "
          f"(top-500 dollar-vol ∪ latest passers ∪ {'/'.join(BENCHMARKS)})")

    limit = params.get("limit")
    if limit:
        universe = universe[: int(limit)]
        print(f"[intraday] params limit={limit} -> pulling {len(universe)} tickers")

    yf_to_canon_full = {yft: tk for tk, yft in _yf_map(con, universe).items()}
    all_yf = list(yf_to_canon_full)

    new_rows = {"1m": 0, "5m": 0}
    got_all: set[str] = set()
    failed_batches = 0

    for interval, period in INTERVALS.items():
        print(f"[intraday] === {interval} bars, period={period} ===")
        got_iv: set[str] = set()
        for batch in _batches(all_yf, BATCH_SIZE):
            sub_map = {y: yf_to_canon_full[y] for y in batch}
            raw = _download(batch, interval=interval, period=period)
            if raw is None or raw.empty:
                failed_batches += 1
            df, got = _extract_long(raw, sub_map, interval)
            n = db.insert_intraday(con, df)
            new_rows[interval] += n
            got_iv |= got
            print(f"[intraday] {interval} batch {len(batch)} -> {n} new rows "
                  f"({len(got)} with data)")
            time.sleep(BATCH_SLEEP)
        got_all |= {yf_to_canon_full[y] for y in got_iv}
        print(f"[intraday] {interval} done: {new_rows[interval]} new rows, "
              f"{len(got_iv)} tickers with data")

    requested = len(all_yf)
    with_data = len(got_all)
    failed = requested - with_data

    # honest accounting -> _meta.json under the 'intraday' key (merge!)
    store_gb = rsc.dir_size_gb(STORE_DIR)
    accounting = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "tickers_requested": requested,
        "tickers_with_data": with_data,
        "new_rows_1m": new_rows["1m"],
        "new_rows_5m": new_rows["5m"],
        "failed_tickers": failed,
        "failed_batches": failed_batches,
        "store_gb": round(store_gb, 2),
    }
    rsc.merge_meta(meta_path, {"intraday": accounting})
    # keep the top-level disk_warning honest on every intraday run too
    rsc.update_disk_warning(meta_path, store_gb)

    print(f"[intraday] DONE requested={requested} with_data={with_data} "
          f"failed={failed} new_1m={new_rows['1m']} new_5m={new_rows['5m']} "
          f"store={store_gb:.2f}GiB")
    return accounting


# --------------------------------------------------------------------------- #
# convenience: enqueue + run through the queue (keeps the one-queue discipline)
# --------------------------------------------------------------------------- #
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Intraday archiver (§12.2).")
    ap.add_argument("--db", default=None, help="DuckDB path (default: store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--params", default="{}", help="params JSON, e.g. '{\"limit\": 40}'")
    args = ap.parse_args()

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)
    run(json.loads(args.params), con, meta_path=args.meta)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
