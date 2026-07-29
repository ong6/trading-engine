#!/usr/bin/env python
"""Corporate actions — splits + dividends collector and split reconciler.

Three modes, one module:

  --mode backfill      full split/dividend history for every ticker in `prices`.
                       A §12.7 job-queue citizen (job kind `actions`): batched,
                       progress-logged, resumable via `actions_fetch_log`.
  --mode incremental   nightly; the small set that actually matters — held names,
                       names with pending orders, the benchmark/sector ETFs, and
                       the latest screen's top-N. Seconds, not hours.
  --mode reconcile     nightly; make the stored price series and the sim books
                       coherent with each newly-discovered split. FATAL on error.

WHY RESTATEMENT (the central design decision — see BUILDLOG):
`prices` is a CACHE OF YAHOO'S SPLIT-ADJUSTED VIEW, not a point-in-time table.
Yahoo restates raw OHLC at fetch time, but `collect.py --incremental` only
re-fetches `period="5d"` with INSERT OR REPLACE, so the first split in any stored
name leaves a permanent scale break a few sessions back: every lookback crossing
it (SMA200, RS ranks, 55d breakout, ATR, 252d vol, 52wk high, 3/6/12-mo returns)
silently corrupts, and the sim books take a fake ~(1−1/ratio) crash that fires
false stops. Controlled, audited restatement to Yahoo's CURRENT convention is how
the cache stays internally coherent.

The professional alternative (QuantConnect LEAN / Quantopian) keeps truly-raw
prices append-only and derives an adjusted VIEW from cumulative factors. That is
not viable here: our stored history is already Yahoo-back-adjusted as of each
row's fetch date, and every incremental re-fetch arrives restated — there is no
raw series to preserve. The append-only guardrail continues to apply in full to
the as_of-stamped point-in-time tables (screen_results, fundamentals,
universe_snapshot, earnings_calendar, intraday_prices, corporate_actions).

NEVER GUESS — the yfinance reliability guards (documented gaps: missing splits
gh#2174/#2183, cap-gain distributions conflated with dividends gh#2666, and
Yahoo occasionally failing to restate past prices at all):
  (a) A split is only applied when the STORED series actually shows the break.
      We locate the break by scanning the one-session close ratios around the
      ex-date for one that matches the reported ratio in log space. Two readings
      are accepted — "break present, restate" and "already restated, no-op" —
      and anything else is logged as skipped_sanity (audit_log WARN + a nightly
      TODO breadcrumb) and left untouched for a human.
  (b) An INDEPENDENT tripwire, run regardless of what actions data says: any
      held-or-pending name whose latest one-session close move exceeds 40% with
      no corporate_actions row nearby is WARNed loudly (possible missed split).

Why the break is searched for rather than assumed to sit at the ex-date: the
nightly 5-day re-fetch restates the last few sessions too, so a split spotted
2–3 sessions late has its scale break at the EDGE OF THE REFETCH WINDOW, not at
the ex-date. Restating `date < ex_date` in that case would double-adjust the
bars in between. We restate `date < break_date`.

Fill-adjustment boundary is different and deliberately so: `split_adjustments`
records the ex_date, because a fill BEFORE the ex-date was economically executed
at pre-split prices whatever the storage boundary turned out to be. That is what
portfolio.rebuild_state replays against.
"""
from __future__ import annotations

import json
import math
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

PER_NAME_SLEEP = 0.35      # politeness pause between per-name .actions requests
RETRY_SLEEP = 15           # one backoff before recording a name as a gap
FLUSH_EVERY = 50           # insert + log progress every N names (resumability)

# Benchmarks and sector sleeves the league depends on — always refreshed nightly.
CORE_ETFS = ["SPY", "EFA", "BIL", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
             "XLP", "XLU", "XLB", "XLRE", "XLC"]

# --- reconciler tolerances (log space) ------------------------------------- #
# A reading is accepted only if it lands within ±20% of one hypothesis...
TOL_LOG = math.log(1.2)
# ...and the two hypotheses (break present / already restated) must be further
# apart than the two tolerance balls, or they overlap and nothing is decidable.
# 2*TOL_LOG = 0.365 -> ratios inside [0.694, 1.44] are ambiguous by construction
# (a 5:4 or 4:3 split; a 3:2 at ln 1.5 = 0.405 is still decidable).
MIN_SEPARATION_LOG = 2 * TOL_LOG
SEARCH_BEFORE = 15         # sessions before ex_date to scan for the break
SEARCH_AFTER = 10          # sessions after ex_date to scan for the break
# Independent tripwire: a one-session move beyond this with no action row nearby.
TRIPWIRE_MOVE = 0.40
TRIPWIRE_NEAR_DAYS = 7     # a corporate_actions row within ±N days explains it


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
def _fetch_actions(yf_ticker: str) -> pd.DataFrame | None:
    """One `.actions` pull with a single backoff retry. Returns the DataFrame
    (possibly empty) or None on hard failure — the caller records a gap and moves
    on; we never loop on a bad name."""
    try:
        return yf.Ticker(yf_ticker).actions
    except Exception:  # noqa: BLE001 - resilient, retry once
        time.sleep(RETRY_SLEEP)
        try:
            return yf.Ticker(yf_ticker).actions
        except Exception:  # noqa: BLE001
            return None


def _rows_from_actions(canon: str, act: pd.DataFrame | None) -> list[dict]:
    """Flatten a yfinance `.actions` frame into corporate_actions rows.

    The index is a tz-aware (exchange-local) DatetimeIndex; the wall-clock date IS
    the ex-date, so we take `.date()` without converting timezones. Zero/NaN cells
    are the frame's padding for "no action of this kind on this date" and are
    dropped — never stored as a fact.
    """
    if act is None or not hasattr(act, "empty") or act.empty:
        return []
    out: list[dict] = []
    for ts, row in act.iterrows():
        try:
            ex = pd.Timestamp(ts).date()
        except Exception:  # noqa: BLE001
            continue
        for col, kind in (("Dividends", "dividend"), ("Stock Splits", "split")):
            if col not in act.columns:
                continue
            v = row.get(col)
            if v is None or pd.isna(v):
                continue
            v = float(v)
            if v <= 0:
                continue
            out.append({"ticker": canon, "ex_date": ex, "kind": kind, "value": v})
    return out


# --------------------------------------------------------------------------- #
# universe selection
# --------------------------------------------------------------------------- #
def _yf_map(con, canon: set[str]) -> list[tuple[str, str]]:
    if not canon:
        return []
    rows = con.execute(
        "SELECT ticker, yf_ticker FROM universe WHERE ticker IN "
        f"({','.join(['?'] * len(canon))})",
        list(canon),
    ).fetchall()
    ymap = {tk: (yft or tk) for tk, yft in rows}
    return sorted((tk, ymap.get(tk, tk)) for tk in canon)


def _select_universe(con, params: dict, mode: str) -> tuple[list[tuple[str, str]], str]:
    """((canonical, yf) pairs, source label). --tickers always wins."""
    tickers = params.get("tickers")
    if tickers:
        if isinstance(tickers, str):
            tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return _yf_map(con, set(tickers)), "explicit-tickers"

    if mode == "backfill":
        rows = con.execute("SELECT DISTINCT ticker FROM prices").fetchall()
        return _yf_map(con, {r[0] for r in rows}), "all-tickers-with-prices"

    # incremental: only what the books and tonight's decisions actually touch.
    canon: set[str] = set(CORE_ETFS)
    canon |= {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM sim_positions WHERE qty > 0").fetchall()}
    canon |= {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM sim_orders WHERE status = 'pending'").fetchall()}
    top_n = int(params.get("top_n", 50))
    max_run = con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
    if max_run is not None and top_n > 0:
        canon |= {r[0] for r in con.execute(
            "SELECT ticker FROM screen_results WHERE run_date = ? AND passes_template "
            "ORDER BY rs_rank DESC, ticker LIMIT ?", [max_run, top_n]).fetchall()}
    # Never ask Yahoo about a name we hold no bars for.
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM prices WHERE ticker IN "
        f"({','.join(['?'] * len(canon))})", list(canon)).fetchall()} if canon else set()
    return _yf_map(con, canon & have), "held ∪ pending ∪ core-ETFs ∪ screen-top-N"


def _already_done(con, on: date) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM actions_fetch_log WHERE fetched_on = ?", [on]
    ).fetchall()}


# --------------------------------------------------------------------------- #
# collection
# --------------------------------------------------------------------------- #
def collect(con, params: dict, mode: str) -> dict:
    """Pull splits + dividends for the mode's universe into corporate_actions.

    Resumable and same-day idempotent: a ticker with an actions_fetch_log row for
    today is skipped (pass resume=False to force a re-pull).
    """
    on = datetime.now(timezone.utc).date()
    pairs, source = _select_universe(con, params, mode)
    limit = params.get("limit")
    if limit:
        pairs = pairs[: int(limit)]

    resume = params.get("resume", True) and mode == "backfill"
    done = _already_done(con, on) if resume else set()
    pending = [(tk, yft) for tk, yft in pairs if tk not in done]
    print(f"[actions] mode={mode} universe={len(pairs)} source='{source}' "
          f"already_done_today={len(done & {tk for tk, _ in pairs})} "
          f"pending={len(pending)}")

    inserted = with_actions = empty = failed = 0
    buf: list[dict] = []
    log_buf: list[dict] = []

    def _flush() -> None:
        nonlocal inserted, buf, log_buf
        if buf:
            inserted += db.upsert_actions(con, pd.DataFrame(buf))
            buf = []
        if log_buf:
            con.executemany(
                "INSERT OR REPLACE INTO actions_fetch_log "
                "(ticker, fetched_on, n_splits, n_dividends, status) "
                "VALUES (?, ?, ?, ?, ?)",
                [[r["ticker"], on, r["n_splits"], r["n_dividends"], r["status"]]
                 for r in log_buf],
            )
            log_buf = []

    for i, (canon, yft) in enumerate(pending, 1):
        act = _fetch_actions(yft)
        if act is None:
            failed += 1
            log_buf.append({"ticker": canon, "n_splits": 0, "n_dividends": 0,
                            "status": "failed"})
        else:
            rows = _rows_from_actions(canon, act)
            n_sp = sum(1 for r in rows if r["kind"] == "split")
            n_dv = sum(1 for r in rows if r["kind"] == "dividend")
            if rows:
                with_actions += 1
                buf.extend(rows)
            else:
                empty += 1
            log_buf.append({"ticker": canon, "n_splits": n_sp, "n_dividends": n_dv,
                            "status": "ok" if rows else "empty"})
        if i % FLUSH_EVERY == 0:
            _flush()
            print(f"[actions] {i}/{len(pending)} pulled (with_actions={with_actions} "
                  f"empty={empty} failed={failed} rows_written={inserted})")
        time.sleep(PER_NAME_SLEEP)
    _flush()

    totals = con.execute(
        "SELECT COUNT(*) FILTER (WHERE kind = 'split'), "
        "       COUNT(*) FILTER (WHERE kind = 'dividend') FROM corporate_actions"
    ).fetchone()
    return {
        "mode": mode,
        "universe": len(pairs),
        "universe_source": source,
        "pulled_this_run": len(pending),
        "with_actions": with_actions,
        "no_actions": empty,
        "failed_tickers": failed,
        "rows_written_this_run": inserted,
        "total_splits": totals[0],
        "total_dividends": totals[1],
    }


# --------------------------------------------------------------------------- #
# split reconciliation
# --------------------------------------------------------------------------- #
def _session_window(con, ticker: str, ex_date: date) -> list[tuple[date, float]]:
    """Stored (date, close) around ex_date: SEARCH_BEFORE sessions before through
    SEARCH_AFTER sessions after, oldest first. Rows with a NULL close are dropped
    (a break can't be measured against a hole)."""
    before = con.execute(
        "SELECT date, close FROM prices WHERE ticker = ? AND date < ? "
        "AND close IS NOT NULL ORDER BY date DESC LIMIT ?",
        [ticker, ex_date, SEARCH_BEFORE],
    ).fetchall()
    after = con.execute(
        "SELECT date, close FROM prices WHERE ticker = ? AND date >= ? "
        "AND close IS NOT NULL ORDER BY date ASC LIMIT ?",
        [ticker, ex_date, SEARCH_AFTER],
    ).fetchall()
    return [(d, float(c)) for d, c in reversed(before)] + \
           [(d, float(c)) for d, c in after]


def _adjudicate(con, ticker: str, ex_date: date, ratio: float) -> dict:
    """Decide what the STORED series says about this split. Never guesses.

    Returns {outcome, break_date, observed}. Outcomes:
      applied_pending  - break located; caller should restate `date < break_date`
      noop_restated    - no break: the store already matches the post-split scale
      noop_pre_history - the split predates our earliest stored bar
      skipped_ambiguous- |ln ratio| too small to tell the two readings apart
      skipped_no_bars  - not enough stored bars around ex_date to measure
      skipped_sanity   - a large unexplained move sits by the ex-date: hands off
    """
    if ratio <= 0:
        return {"outcome": "skipped_sanity", "break_date": None, "observed": None}
    lr = math.log(ratio)
    if abs(lr) < MIN_SEPARATION_LOG:
        return {"outcome": "skipped_ambiguous", "break_date": None, "observed": None}

    first_bar = con.execute(
        "SELECT MIN(date) FROM prices WHERE ticker = ?", [ticker]).fetchone()[0]
    if first_bar is None:
        return {"outcome": "skipped_no_bars", "break_date": None, "observed": None}
    if first_bar >= ex_date:
        # Nothing stored before the split — there is no pre-split scale to fix.
        return {"outcome": "noop_pre_history", "break_date": None, "observed": None}

    win = _session_window(con, ticker, ex_date)
    if len(win) < 2:
        return {"outcome": "skipped_no_bars", "break_date": None, "observed": None}

    # One-session close ratios: r[i] = close(i-1) / close(i). At the scale break
    # r == ratio (old scale over new scale), for a forward AND a reverse split.
    best = None       # (distance_to_ex_date, break_date, observed) matching `ratio`
    worst_move = 0.0  # largest |ln r| seen adjacent to the ex-date
    for i in range(1, len(win)):
        prev_d, prev_c = win[i - 1]
        cur_d, cur_c = win[i]
        if prev_c <= 0 or cur_c <= 0:
            continue
        obs = prev_c / cur_c
        lo = math.log(obs)
        if abs(lo - lr) <= TOL_LOG:
            key = abs((cur_d - ex_date).days)
            if best is None or key < best[0]:
                best = (key, cur_d, obs)
        if abs((cur_d - ex_date).days) <= 4:
            worst_move = max(worst_move, abs(lo))

    if best is not None:
        return {"outcome": "applied_pending", "break_date": best[1],
                "observed": best[2]}
    if worst_move > MIN_SEPARATION_LOG:
        # Something big happened right by the ex-date but it does NOT match the
        # reported ratio. Yahoo's split row or its restatement may be wrong
        # (gh#2174/#2183). Never guess — leave it and surface it.
        return {"outcome": "skipped_sanity", "break_date": None,
                "observed": math.exp(worst_move)}
    return {"outcome": "noop_restated", "break_date": None, "observed": None}


def _audit(con, action: str, payload: dict) -> None:
    con.execute(
        "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
        [datetime.now(timezone.utc), "actions.reconcile", action,
         json.dumps(payload, default=str)],
    )


def _restate(con, ticker: str, ex_date: date, ratio: float, break_date: date) -> int:
    """Restate the ticker's pre-break bars to the post-split scale and adjust the
    sim books, in ONE transaction with the watermark row. Returns rows restated.

    Prices: open/high/low/close ÷ ratio, volume × ratio for `date < break_date`.
    Sim:    sim_positions.qty × ratio, avg_cost ÷ ratio (book value invariant);
            pending sim_orders.qty × ratio (an unfilled intent is re-scaled too).
    """
    n = con.execute(
        "SELECT COUNT(*) FROM prices WHERE ticker = ? AND date < ?",
        [ticker, break_date]).fetchone()[0]
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            "UPDATE prices SET open = open / ?, high = high / ?, low = low / ?, "
            "close = close / ?, volume = CAST(ROUND(volume * ?) AS BIGINT) "
            "WHERE ticker = ? AND date < ?",
            [ratio, ratio, ratio, ratio, ratio, ticker, break_date],
        )
        con.execute(
            "UPDATE sim_positions SET qty = qty * ?, avg_cost = avg_cost / ? "
            "WHERE ticker = ? AND qty != 0",
            [ratio, ratio, ticker],
        )
        con.execute(
            "UPDATE sim_orders SET qty = qty * ? WHERE ticker = ? AND status = 'pending'",
            [ratio, ticker],
        )
        con.execute(
            "INSERT OR REPLACE INTO split_adjustments (ticker, ex_date, ratio, "
            "outcome, observed, break_date, rows_restated, applied_at) "
            "VALUES (?, ?, ?, 'applied', ?, ?, ?, ?)",
            [ticker, ex_date, ratio, ratio, break_date, n,
             datetime.now(timezone.utc)],
        )
        _audit(con, "split_restated", {
            "ticker": ticker, "ex_date": ex_date, "ratio": ratio,
            "break_date": break_date, "rows_restated": n,
        })
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


def _mark(con, ticker: str, ex_date: date, ratio: float, verdict: dict) -> None:
    con.execute(
        "INSERT OR REPLACE INTO split_adjustments (ticker, ex_date, ratio, "
        "outcome, observed, break_date, rows_restated, applied_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        [ticker, ex_date, ratio, verdict["outcome"], verdict["observed"],
         verdict["break_date"], datetime.now(timezone.utc)],
    )


def tripwire(con) -> list[str]:
    """Guard (b) — independent of any corporate_actions data.

    Any held-or-pending name whose most recent one-session close move exceeds
    TRIPWIRE_MOVE with no corporate_actions row within ±TRIPWIRE_NEAR_DAYS is a
    possible MISSED split. Returns the warning lines (also printed)."""
    names = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM sim_positions WHERE qty > 0 "
        "UNION SELECT DISTINCT ticker FROM sim_orders WHERE status = 'pending'"
    ).fetchall()]
    warns: list[str] = []
    for tk in sorted(names):
        rows = con.execute(
            "SELECT date, close FROM prices WHERE ticker = ? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT 2", [tk]).fetchall()
        if len(rows) < 2 or not rows[1][1]:
            continue
        d, c = rows[0][0], float(rows[0][1])
        pc = float(rows[1][1])
        if pc <= 0:
            continue
        move = c / pc - 1
        if abs(move) <= TRIPWIRE_MOVE:
            continue
        near = con.execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE ticker = ? "
            "AND ex_date BETWEEN ? - INTERVAL 7 DAY AND ? + INTERVAL 7 DAY",
            [tk, d, d]).fetchone()[0]
        if near:
            continue
        line = (f"WARN tripwire: {tk} moved {move * 100:+.1f}% on {d} with no "
                f"corporate_actions row within {TRIPWIRE_NEAR_DAYS}d — possible "
                f"missed split")
        warns.append(line)
        print(f"[actions] {line}")
        _audit(con, "tripwire_unexplained_move",
               {"ticker": tk, "date": d, "move": move})
    return warns


def reconcile(con) -> dict:
    """Adjudicate every not-yet-considered split with ex_date <= the latest bar,
    restating where the stored series genuinely shows the break. Idempotent: the
    split_adjustments watermark means each split is decided exactly once."""
    latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if latest is None:
        print("[actions] reconcile: prices table is empty; nothing to do")
        return {"candidates": 0}

    cands = con.execute(
        "SELECT c.ticker, c.ex_date, c.value FROM corporate_actions c "
        "LEFT JOIN split_adjustments s ON s.ticker = c.ticker AND s.ex_date = c.ex_date "
        "WHERE c.kind = 'split' AND c.ex_date <= ? AND s.ticker IS NULL "
        "ORDER BY c.ex_date, c.ticker",
        [latest],
    ).fetchall()
    print(f"[actions] reconcile: {len(cands)} unadjudicated split(s) "
          f"with ex_date <= {latest}")

    counts: dict[str, int] = {}
    restated_rows = 0
    todos: list[str] = []
    for tk, ex, ratio in cands:
        ratio = float(ratio)
        v = _adjudicate(con, tk, ex, ratio)
        outcome = v["outcome"]
        if outcome == "applied_pending":
            n = _restate(con, tk, ex, ratio, v["break_date"])
            restated_rows += n
            outcome = "applied"
            print(f"[actions] RESTATED {tk} split {ratio:g}:1 ex={ex} "
                  f"break={v['break_date']} rows={n} (obs {v['observed']:.4f}) "
                  f"— positions/pending orders rescaled")
        else:
            _mark(con, tk, ex, ratio, v)
            if outcome.startswith("skipped"):
                line = (f"WARN {outcome}: {tk} split {ratio:g}:1 ex={ex} "
                        f"(observed {v['observed']}) — NOT restated, needs a human")
                todos.append(line)
                print(f"[actions] {line}")
                _audit(con, f"split_{outcome}",
                       {"ticker": tk, "ex_date": ex, "ratio": ratio,
                        "observed": v["observed"]})
        counts[outcome] = counts.get(outcome, 0) + 1

    todos += tripwire(con)
    summary = {"candidates": len(cands), "rows_restated": restated_rows,
               "outcomes": counts, "warnings": len(todos)}
    print(f"[actions] reconcile DONE: {counts or '{}'} rows_restated={restated_rows}")
    if todos:
        print(f"TODO: corporate actions need review ({len(todos)}):")
        for t in todos:
            print(f"TODO:   {t}")
    return summary


# --------------------------------------------------------------------------- #
# entry point the queue dispatches to
# --------------------------------------------------------------------------- #
def run(params: dict | None, con, meta_path: str | Path = DEFAULT_META) -> dict:
    """§12.7 job entry. params: mode ('backfill'|'incremental'|'reconcile'),
    tickers, limit, top_n, resume."""
    params = params or {}
    db.init_actions_schema(con)
    # incremental universe selection and the reconciler both read (and, on a
    # restatement, write) sim_positions / sim_orders / audit_log — make sure they
    # exist when the queue dispatches us against a store sim has never touched.
    sys.path.insert(0, str(REPO_ROOT))
    from sim.schema import init_sim_schema  # noqa: E402
    init_sim_schema(con)
    mode = params.get("mode", "backfill")

    if mode == "reconcile":
        acc = reconcile(con)
    else:
        acc = collect(con, params, mode)
        if params.get("reconcile", False):
            acc["reconcile"] = reconcile(con)

    store_gb = rsc.dir_size_gb(STORE_DIR)
    acc["last_run"] = datetime.now(timezone.utc).isoformat()
    acc["store_gb"] = round(store_gb, 2)
    rsc.merge_meta(meta_path, {f"actions_{mode}": acc})
    rsc.update_disk_warning(meta_path, store_gb)
    return acc


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Corporate actions (splits + dividends).")
    ap.add_argument("--mode", default="incremental",
                    choices=["backfill", "incremental", "reconcile"])
    ap.add_argument("--db", default=None, help="DuckDB path (default store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--tickers", default=None, help="comma list, e.g. SPY,BIL")
    ap.add_argument("--limit", type=int, default=None, help="cap to first N names")
    ap.add_argument("--top-n", type=int, default=50,
                    help="screen passers to include in incremental mode")
    ap.add_argument("--no-resume", action="store_true",
                    help="re-pull names already fetched today (backfill)")
    args = ap.parse_args()

    params: dict = {"mode": args.mode, "top_n": args.top_n,
                    "resume": not args.no_resume}
    if args.tickers:
        params["tickers"] = args.tickers
    if args.limit:
        params["limit"] = args.limit

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)
    run(params, con, meta_path=args.meta)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
