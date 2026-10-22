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
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from engine.lib import db
from engine.lib import resources as rsc
from engine.lib.log import get_logger
from engine.lib.settings import META_PATH as DEFAULT_META
from engine.lib.settings import STORE_DIR
from sim import nyse
from tools.stage_timings import record_flow, writer_connection

log = get_logger("intraday")

BENCHMARKS = ["SPY", "QQQ", "IWM"]
BATCH_SIZE = 50
BATCH_SLEEP = 1.5          # politeness pause between batches
RETRY_SLEEP = 20           # one backoff before recording a batch as a gap

# yfinance intraday intervals -> pull window (free-tier limits)
INTERVALS = {"1m": "7d", "5m": "60d"}
# Per-ticker, per-session completed coverage, relative to `_meta.json`'s directory.
# It is rewritten in place after every batch; `_meta.json` carries only a pointer.
COVERAGE_REPORT = "reports/producer-detail/intraday-coverage.json"

_YF_FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


# --------------------------------------------------------------------------- #
# universe selection
# --------------------------------------------------------------------------- #
def _select_universe(con) -> list[str]:
    """Canonical tickers to archive: liquidity top-500 ∪ latest passers ∪ ETFs."""
    top = con.execute(
        """
        WITH recent AS (
            SELECT p.ticker, p.close, p.volume,
                   ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
            FROM prices p
            JOIN universe u ON u.ticker = p.ticker
            -- bound the window function's input: 40 calendar days covers the 20
            -- sessions we keep, so ROW_NUMBER() never scans the full prices table
            WHERE u.active AND u.liquid
              AND p.date >= (SELECT MAX(date) FROM prices) - INTERVAL 40 DAY
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
    out = sub.reindex(columns=["ts", "Open", "High", "Low", "Close", "Volume"]).rename(columns=_YF_FIELDS)
    out["ticker"] = canon
    out["interval"] = interval
    out["ts"] = _to_utc(out["ts"])
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


def _download(yf_tickers: list[str], *, interval: str, period: str | None = None,
              start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
    """One yf.download intraday call with a single backoff retry on exception.
    An empty frame is returned on double-failure — the caller records the gap."""
    kwargs = dict(interval=interval, group_by="ticker",
                  auto_adjust=False, threads=True, progress=False)
    kwargs.update(period=period) if start is None else kwargs.update(start=start, end=end)
    try:
        return yf.download(yf_tickers, **kwargs)
    except Exception as exc:  # noqa: BLE001 - be resilient, retry once
        log.warning(f"[intraday] {interval} batch failed ({exc}); retry in {RETRY_SLEEP}s")
        time.sleep(RETRY_SLEEP)
        try:
            return yf.download(yf_tickers, **kwargs)
        except Exception as exc2:  # noqa: BLE001
            log.warning(f"[intraday] {interval} batch retry failed ({exc2}); recording gap")
            return pd.DataFrame()


def _saved_coverage(meta_path) -> dict:
    """Coverage from the report; a run before the report existed kept it in `_meta.json`."""
    try:
        saved = json.loads((Path(meta_path).parent / COVERAGE_REPORT).read_text())
    except FileNotFoundError:
        return rsc.read_meta(meta_path).get("intraday", {}).get("coverage", {})
    except (OSError, json.JSONDecodeError):
        return {}
    return saved.get("coverage", {}) if isinstance(saved, dict) else {}


def _save_coverage(meta_path, completed: dict) -> None:
    rsc.write_text_atomic(Path(meta_path).parent / COVERAGE_REPORT, json.dumps(
        {"coverage": completed}, sort_keys=True, separators=(",", ":")) + "\n")


def _coverage(con, mapping: dict[str, str], meta_path, now: datetime) -> dict:
    """Validate completed response coverage against resident per-session counts.

    A high watermark alone cannot detect a deleted interior session. Counts are
    saved only after insertion; legacy state and incomplete responses fetch full.
    """
    saved = _saved_coverage(meta_path)
    if not mapping or not isinstance(saved, dict) or not saved:
        return {}
    rows = con.execute(
        "SELECT ticker, interval, CAST(ts AS DATE), count(*) "
        "FROM intraday_prices WHERE ticker = ANY(?) AND ts >= ? "
        "GROUP BY ticker, interval, CAST(ts AS DATE)",
        [list(mapping.values()), datetime.combine(
            (now - timedelta(days=60)).date(), datetime.min.time())],
    ).fetchall()
    resident = {(tk, iv, day.isoformat()): n for tk, iv, day, n in rows}
    valid = {}
    for iv, period in INTERVALS.items():
        floor = (now - timedelta(days=int(period[:-1]))).date().isoformat()
        for tk, item in saved.get(iv, {}).items():
            try:
                through = datetime.fromisoformat(item["through"])
                days = {d: n for d, n in item["days"].items() if d >= floor}
                if (days and through.date().isoformat() >= floor
                        and all(resident.get((tk, iv, d)) == n
                                for d, n in days.items())):
                    valid.setdefault(iv, {})[tk] = item
            except (KeyError, TypeError, ValueError):
                continue
    return valid


def _completed_coverage(frame, interval, start, now, previous):
    """Trust only responses spanning every completed exchange session requested."""
    days = dict(previous.get("days", {})) if previous else {}
    if not frame.empty:
        days.update({d.isoformat(): int(n) for d, n in
                     frame.groupby(frame.ts.dt.date).size().items()})
    last = now.date()
    # session_close includes early closes, and UTC conversion includes DST.
    from zoneinfo import ZoneInfo
    def close(day):
        return datetime.combine(day, nyse.session_close(day), ZoneInfo("America/New_York")).astimezone(timezone.utc)
    while not nyse.is_session(last) or close(last) > now:
        last -= timedelta(days=1)
    expected = []
    day = start.date()
    while day <= last:
        if nyse.is_session(day) and start < close(day):
            expected.append(day.isoformat())
        day += timedelta(days=1)
    if not expected or any(not days.get(d) for d in expected) or frame.empty:
        return None
    end = frame.ts.max().to_pydatetime().replace(tzinfo=timezone.utc)
    if end < close(last) - timedelta(minutes=int(interval[:-1])):
        return None
    floor = (now - timedelta(days=int(INTERVALS[interval][:-1]))).date().isoformat()
    return {"through": datetime.combine(last, datetime.min.time()).isoformat(),
            "days": {d: n for d, n in days.items() if d >= floor}}


# --------------------------------------------------------------------------- #
# preparation + network loop
# --------------------------------------------------------------------------- #
def _prepare_run(con, params: dict) -> dict[str, str]:
    """Resolve the archive universe while a database connection is available."""
    universe = _select_universe(con)
    log.info(f"[intraday] archive universe: {len(universe)} tickers "
          f"(top-500 dollar-vol ∪ latest passers ∪ {'/'.join(BENCHMARKS)})")

    limit = params.get("limit")
    if limit is not None:
        universe = universe[: int(limit)]
        log.info(f"[intraday] params limit={limit} -> pulling {len(universe)} tickers")

    return {yft: tk for tk, yft in _yf_map(con, universe).items()}


def _pull_batches(
    yf_to_canon_full: dict[str, str],
    insert_batch: Callable[[pd.DataFrame], int],
    meta_path: str | Path,
    coverage: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Download, parse, and checkpoint batches without retaining a DB handle."""
    all_yf = list(yf_to_canon_full)

    new_rows = {"1m": 0, "5m": 0}
    got_all: set[str] = set()
    failed_batches = 0

    now = now or datetime.now(timezone.utc)
    coverage = coverage or {}
    completed = {iv: dict(items) for iv, items in coverage.items()}
    fetched_rows = 0
    payload_bytes = 0
    for interval, period in INTERVALS.items():
        floor = now - timedelta(days=int(period[:-1]))
        groups = {}
        for yft in all_yf:
            tk = yf_to_canon_full[yft]
            item = coverage.get(interval, {}).get(tk)
            start = datetime.fromisoformat(item["through"]).replace(tzinfo=timezone.utc) if item else None
            groups.setdefault(start, []).append(yft)
        got_iv = set()
        for start, names in groups.items():
            for batch in _batches(names, BATCH_SIZE):
                sub_map = {y: yf_to_canon_full[y] for y in batch}
                raw = (_download(batch, interval=interval, period=period) if start is None
                       else _download(batch, interval=interval, start=start, end=now))
                df, got = _extract_long(raw, sub_map, interval)
                # A failed/partial incremental batch retries missing symbols with
                # the full provider window, rather than claiming gap completion.
                attempts = [(df, got, start)]
                missing = [y for y in batch if y not in got or (
                    start is not None and _completed_coverage(
                        df[df.ticker == sub_map[y]], interval, start, now,
                        coverage.get(interval, {}).get(sub_map[y])) is None)]
                if missing:
                    failed_batches += 1
                    if start is not None:
                        full, full_got = _extract_long(
                            _download(missing, interval=interval, period=period),
                            {y: sub_map[y] for y in missing}, interval)
                        attempts.append((full, full_got, None))
                for frame, received, request_start in attempts:
                    fetched_rows += len(frame)
                    size = int(frame.memory_usage(index=True, deep=True).sum())
                    payload_bytes += size
                    n = insert_batch(frame)
                    record_flow(input_rows=len(frame), output_rows=n, input_bytes=size)
                    new_rows[interval] += n
                    got_iv |= received
                    for y in batch:
                        tk = sub_map[y]
                        if y not in received:
                            if y in missing:
                                completed.setdefault(interval, {}).pop(tk, None)
                            continue
                        sub = frame[frame.ticker == tk]
                        item = _completed_coverage(sub, interval, request_start or floor, now,
                                                   coverage.get(interval, {}).get(tk) if request_start else None)
                        if item:
                            completed.setdefault(interval, {})[tk] = item
                        else:
                            completed.setdefault(interval, {}).pop(tk, None)
                    # Save after the DB commit. A crash before this leaves old
                    # coverage, which conservatively repeats the overlap.
                    _save_coverage(meta_path, completed)
                time.sleep(BATCH_SLEEP)
        got_all |= {yf_to_canon_full[y] for y in got_iv}

    requested = len(all_yf)
    with_data = len(got_all)
    failed = requested - with_data

    # honest accounting -> _meta.json under the 'intraday' key (merge!)
    store_gb = rsc.live_store_gb(STORE_DIR)
    accounting = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "tickers_requested": requested,
        "tickers_with_data": with_data,
        "new_rows_1m": new_rows["1m"],
        "new_rows_5m": new_rows["5m"],
        "failed_tickers": failed,
        "failed_batches": failed_batches,
        "store_gb": round(store_gb, 2),
        "coverage_report": {"path": COVERAGE_REPORT,
                            "tickers": {iv: len(completed.get(iv, {})) for iv in INTERVALS}},
        "fetched_rows": fetched_rows,
        "payload_bytes": payload_bytes,
    }
    _save_coverage(meta_path, completed)
    rsc.merge_meta(meta_path, {"intraday": accounting})
    # keep the top-level disk_warning honest on every intraday run too
    rsc.update_disk_warning(meta_path, store_gb, snapshots_gb=rsc.snapshots_gb(STORE_DIR))

    log.info(f"[intraday] DONE requested={requested} with_data={with_data} "
          f"failed={failed} new_1m={new_rows['1m']} new_5m={new_rows['5m']} "
          f"store={store_gb:.2f}GiB")
    return accounting


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """Pull and append intraday bars using an already-owned DB connection.

    This compatibility entry point retains the caller's connection. Queue and
    CLI execution use :func:`run_connection_narrowed` below.
    """
    prepared = _prepare_run(con, params or {})
    now = datetime.now(timezone.utc)
    coverage = _coverage(con, prepared, meta_path, now)
    return _pull_batches(
        prepared,
        lambda frame: db.insert_intraday(con, frame),
        meta_path, coverage, now,
    )


def run_connection_narrowed(
    params: dict | None,
    db_path: str | Path | None = None,
    meta_path: str | Path = DEFAULT_META,
) -> dict:
    """Pull intraday bars without holding DuckDB during HTTP or batch sleeps.

    The queue remains process-level sequential. DuckDB is leased briefly for
    schema/universe preparation and once per completed batch insertion, which
    lets API/UI readers reconnect throughout the network-bound collection.
    """
    path = Path(db_path) if db_path is not None else db.DEFAULT_DB
    with writer_connection(path) as con:
        db.init_schema(con)
        db.init_queue_schema(con)
        prepared = _prepare_run(con, params or {})
        now = datetime.now(timezone.utc)
        coverage = _coverage(con, prepared, meta_path, now)

    def insert_batch(frame: pd.DataFrame) -> int:
        if frame is None or frame.empty:
            return 0
        with writer_connection(path) as write_con:
            return db.insert_intraday(write_con, frame)

    return _pull_batches(prepared, insert_batch, meta_path, coverage, now)


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

    run_connection_narrowed(
        json.loads(args.params), db_path=args.db, meta_path=args.meta
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
