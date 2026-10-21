#!/usr/bin/env python
"""Corporate actions — splits + dividends collector and split reconciler.

Three modes, one module:

  --mode backfill      full split/dividend history for every ticker in `prices`.
                       A §12.7 job-queue citizen (job kind `actions`): batched,
                       progress-logged, resumable via `actions_fetch_log`.
  --mode incremental   nightly; the small set that actually matters — held names,
                       names with pending orders, the benchmark/sector ETFs, the
                       latest screen's top-N, and any name whose re-fetch just
                       rewrote stored bars by a split-sized ratio. Seconds, not hours.
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
      ex-date for one that matches the reported ratio in log space (±8%), and
      the match must sit within BREAK_NEAR_EX_SESSIONS of the ex-date AND the
      bars before it must have been first stored BEFORE the ex-date (otherwise Yahoo
      had already restated them when we fetched them, and the jump is a real
      move). Two readings are accepted — "break present, restate" and "already
      restated, no-op" — and anything else is logged as skipped_* (audit_log
      WARN + a nightly TODO breadcrumb) and left untouched for a human. See
      `_adjudicate` for the full rule and the 2026-09-02 incident behind it.
  (b) An INDEPENDENT tripwire, run regardless of what actions data says: any
      held-or-pending name whose latest one-session close move exceeds 40% with
      no corporate_actions row nearby is WARNed loudly (possible missed split).
      A second pass (`scan_breaks`) reads the recent bars of the whole liquid
      universe: a split-ratio break with a matching volume shift and no restated
      split row, or a split-sized single-bar glitch, puts the name in
      price_quarantine (buys refused) for a human. Added after the 2026-10 gap:
      IESC 685.04 -> 324.12 went unflagged, and CRWU and ETHA were bought on
      mixed bases left by a skipped split.

COVERAGE. The incremental fetch also pulls a rotating 1/ROLLING_SLICES of the
liquid universe each run, so every liquid name is asked about at least weekly.
Without it a name fell out of the fetch set exactly when its unrecorded split
made it look like a crash and fail the screen template.

A LATE RESTATEMENT (DXJ 3:1, ex 2026-10-09): Yahoo served the old scale on the
ex-date evening and restated a night later, so the 5d re-fetch rewrote three
stored bars by the ratio and left the bar before them, stored ON the ex-date, on
the old scale. collect records each such rewrite (`record_split_like_rewrites`,
an append-only audit_log row) before overwriting; the nightly fetch then asks
about that name, and rule 3 accepts the rewrite as proof the pre-break bars were
stored on the old scale. Without that record the reconciler still never guesses.

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
import statistics
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import yfinance as yf

from engine.lib import db
from engine.lib import resources as rsc
from engine.lib.data_quality import observation_reasons
from engine.lib.log import get_logger
from engine.lib.settings import META_PATH as DEFAULT_META
from engine.lib.settings import STORE_DIR
from engine.lib.util import table_exists

log = get_logger("actions")

PER_NAME_SLEEP = 0.35      # politeness pause between per-name .actions requests
RETRY_SLEEP = 15           # one backoff before recording a name as a gap
FLUSH_EVERY = 50           # insert + log progress every N names (resumability)

# Benchmarks and sector sleeves the league depends on — always refreshed nightly.
CORE_ETFS = ["SPY", "EFA", "BIL", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
             "XLP", "XLU", "XLB", "XLRE", "XLC"]

# --- reconciler tolerances (log space) ------------------------------------- #
# The observed one-session close ratio must land within ±8% (log space) of the
# reported split ratio. A split is an EXACT ratio; 8% absorbs the stock's own
# move on the break session and nothing more. The original ±20% band let a 3:2
# split match any −20%…−44% day, which is how three ordinary earnings crashes
# (BH 2018-04-27, ORCL 1999-03-12, NEM 1987-10-16) were accepted as "the break"
# and 14,816 pre-break rows were divided by 1.5 (found by the 2026-09-02 audit).
TOL_LOG = math.log(1.08)
# Ratios too close to 1 cannot be told apart from an ordinary move even at the
# ex-date, so anything inside [1/1.44, 1.44] (1.1:1, 5:4, 4:3, …) is ambiguous
# by construction and skipped. This band is deliberately NOT derived from
# TOL_LOG any more: tightening the match tolerance must not widen the set of
# splits the reconciler is willing to decide. (Unchanged value: 2·ln 1.2.)
MIN_SEPARATION_LOG = math.log(1.44)
SEARCH_BEFORE = 15         # sessions before ex_date to scan for the break
SEARCH_AFTER = 10          # sessions after ex_date to scan for the break
# A genuine break can only sit at the ex-date or at the edge of the nightly 5d
# re-fetch window just before it (see module docstring). Anything further away
# is a real price move, whatever its size.
BREAK_NEAR_EX_SESSIONS = 5
# ...except when the split is recent and collection had an outage: the first
# bar re-fetched after the gap carries the break, which can then sit AFTER the
# ex-date by more than the near window. Only allowed while ex_date is within
# this many sessions of the latest stored bar.
RECENT_EX_SESSIONS = 10
# Independent tripwire: a one-session move beyond this with no action row nearby.
TRIPWIRE_MOVE = 0.40
TRIPWIRE_NEAR_DAYS = 7     # a corporate_actions row within ±N days explains it
TODO_LOG_CAP = 20          # TODO breadcrumbs printed per run (audit_log has all)
# Re-fetch rewrite evidence (audit_log rows written by collect before an overwrite):
# a stored close replaced by one at least the ambiguity band away is split-like.
REWRITE_ACTOR = "collect"
REWRITE_ACTION = "split_like_rewrite"
REWRITE_RECENT_DAYS = 14   # how long a rewrite keeps its name in the nightly fetch
# Incremental runs also pull the liquid names whose crc32 bucket matches the run
# date's ordinal mod this: five consecutive weekday runs cover every bucket.
ROLLING_SLICES = 5
# Liquid-universe break scan (scan_breaks): sessions checked per run, the bars on
# each side of a break whose median volume must shift by the price ratio, and
# the split ratios (and their inverses) a scale break can take.
SCAN_SESSIONS = 10
VOLUME_SESSIONS = 5
SCAN_RATIOS = (1.5, 2.0, 3.0, 4.0, 5.0, 10.0)
QUARANTINE_SPLIT = "suspected_unrecorded_split"
QUARANTINE_GLITCH = "single_bar_glitch"


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
# re-fetch rewrite evidence
# --------------------------------------------------------------------------- #
def record_split_like_rewrites(con, frame: pd.DataFrame) -> list[str]:
    """Before `frame` overwrites stored bars, append one audit_log row per ticker
    whose stored close it replaces by a split-sized ratio (|ln r| >= the
    ambiguity band). Payload: the rewritten dates, the median stored/incoming
    close ratio, and the latest fetched_at of the replaced bars — the source was
    still serving the old scale when they were stored. Returns the tickers."""
    if frame is None or frame.empty or not table_exists(con, "prices"):
        return []
    incoming = frame[["ticker", "date", "close"]].dropna()
    with db.registered_frame(con, "_incoming_split_check", incoming):
        rows = con.execute(
            "SELECT i.ticker, i.date, p.close, i.close, p.fetched_at "
            "FROM _incoming_split_check i JOIN prices p "
            "ON p.ticker = i.ticker AND p.date = i.date "
            "WHERE p.close > 0 AND i.close > 0 AND abs(ln(p.close / i.close)) >= ? "
            "ORDER BY i.ticker, i.date",
            [MIN_SEPARATION_LOG],
        ).fetchall()
    by_ticker: dict[str, list[tuple]] = {}
    for ticker, day, old, new, stored_at in rows:
        by_ticker.setdefault(ticker, []).append((day, float(old) / float(new), stored_at))
    if not by_ticker:
        return []
    if not table_exists(con, "audit_log"):
        from sim.schema import init_sim_schema
        init_sim_schema(con)
    for ticker, items in by_ticker.items():
        stored = [s for _d, _r, s in items if s is not None]
        payload = {
            "ticker": ticker,
            "dates": [d.isoformat() for d, _r, _s in items],
            "ratio": statistics.median(r for _d, r, _s in items),
            "replaced_fetched_at": max(stored).isoformat() if stored else None,
        }
        con.execute(
            "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
            [datetime.now(timezone.utc), REWRITE_ACTOR, REWRITE_ACTION,
             json.dumps(payload, sort_keys=True)],
        )
        log.info(f"[actions] split-like rewrite: {ticker} {payload['dates'][0]}.."
                 f"{payload['dates'][-1]} stored/new {payload['ratio']:.4f}")
    return sorted(by_ticker)


def _rewrites(con, ticker: str | None = None, *, recent: bool = False) -> list[dict]:
    if not table_exists(con, "audit_log"):
        return []
    sql = "SELECT payload FROM audit_log WHERE actor = ? AND action = ?"
    args: list = [REWRITE_ACTOR, REWRITE_ACTION]
    if ticker is not None:
        sql += " AND json_extract_string(payload, '$.ticker') = ?"
        args.append(ticker)
    if recent:
        sql += " AND ts >= ?"
        args.append(datetime.now(timezone.utc) - timedelta(days=REWRITE_RECENT_DAYS))
    return [json.loads(row[0]) for row in con.execute(sql + " ORDER BY ts", args).fetchall()]


def _rewrite_shows_old_scale(con, ticker: str, ratio: float, break_date: date,
                             stored_at: datetime) -> bool:
    """Rule 3's evidence for a late restatement: a recorded re-fetch rewrite by
    this split's ratio that starts exactly at the stored break and replaced bars
    stored no earlier than the pre-break bars, so those were stored on the old
    scale whatever their fetch date."""
    lr = math.log(ratio)
    return any(
        r.get("dates") and r.get("replaced_fetched_at") and r.get("ratio", 0) > 0
        and abs(math.log(r["ratio"]) - lr) <= TOL_LOG
        and date.fromisoformat(r["dates"][0]) == break_date
        and datetime.fromisoformat(r["replaced_fetched_at"]) >= stored_at
        for r in _rewrites(con, ticker)
    )


def _unexplained_rewrites(con) -> list[str]:
    """Recent split-like rewrites with no split row near them: Yahoo restated a
    name's history but its actions feed has not reported the split (yet)."""
    warns = []
    for r in _rewrites(con, recent=True):
        first, last = date.fromisoformat(r["dates"][0]), date.fromisoformat(r["dates"][-1])
        near = con.execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE ticker = ? AND kind = 'split' "
            "AND ex_date BETWEEN ? AND ?",
            [r["ticker"], first - timedelta(days=TRIPWIRE_NEAR_DAYS),
             last + timedelta(days=TRIPWIRE_NEAR_DAYS)],
        ).fetchone()[0]
        if not near:
            line = (f"WARN split-like rewrite: {r['ticker']} {first}..{last} re-fetched "
                    f"at stored/new {r['ratio']:.4f} with no split row within "
                    f"{TRIPWIRE_NEAR_DAYS}d — not restated, needs a human")
            warns.append(line)
            log.info(f"[actions] {line}")
    return warns


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


def _rolling_slice(con, on: date, slices: int) -> set[str]:
    """Liquid names in today's rotation bucket (crc32 is stable across runs)."""
    if slices <= 0 or not table_exists(con, "universe"):
        return set()
    k = on.toordinal() % slices
    return {r[0] for r in con.execute("SELECT ticker FROM universe WHERE liquid").fetchall()
            if zlib.crc32(r[0].encode()) % slices == k}


def _select_universe(con, params: dict, mode: str,
                     on: date | None = None) -> tuple[list[tuple[str, str]], str]:
    """((canonical, yf) pairs, source label). --tickers always wins."""
    tickers = params.get("tickers")
    if tickers:
        if isinstance(tickers, str):
            tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return _yf_map(con, set(tickers)), "explicit-tickers"

    if mode == "backfill":
        rows = con.execute("SELECT DISTINCT ticker FROM prices").fetchall()
        return _yf_map(con, {r[0] for r in rows}), "all-tickers-with-prices"

    # incremental: only what active books and tonight's decisions actually touch.
    canon: set[str] = set(CORE_ETFS)
    canon |= {r[0] for r in con.execute(
        "SELECT DISTINCT p.ticker FROM sim_positions p "
        "JOIN portfolios pf ON pf.id = p.portfolio_id "
        "WHERE pf.active AND p.qty > 0").fetchall()}
    canon |= {r[0] for r in con.execute(
        "SELECT DISTINCT o.ticker FROM sim_orders o "
        "JOIN portfolios pf ON pf.id = o.portfolio_id "
        "WHERE pf.active AND o.status = 'pending'").fetchall()}
    top_n = int(params.get("top_n", 50))
    max_run = con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
    if max_run is not None and top_n > 0:
        canon |= {r[0] for r in con.execute(
            "SELECT ticker FROM screen_results WHERE run_date = ? AND passes_template "
            "ORDER BY rs_rank DESC, ticker LIMIT ?", [max_run, top_n]).fetchall()}
    canon |= {r["ticker"] for r in _rewrites(con, recent=True)}
    if table_exists(con, "price_observation_rejects"):
        canon |= {r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM price_observation_rejects "
            "WHERE reason='basis_unverified' AND recorded_at >= current_timestamp - INTERVAL 14 DAY"
        ).fetchall()}
    canon |= _rolling_slice(con, on or datetime.now(timezone.utc).date(),
                            int(params.get("rolling_slices", ROLLING_SLICES)))
    # Never ask Yahoo about a name we hold no bars for.
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM prices WHERE ticker IN "
        f"({','.join(['?'] * len(canon))})", list(canon)).fetchall()} if canon else set()
    return _yf_map(con, canon & have), (
        "active-held ∪ active-pending ∪ core-ETFs ∪ screen-top-N ∪ split-like-rewrites"
        " ∪ liquid-rolling-slice")


def _already_done(con, on: date) -> set[str]:
    """Tickers with a completed pull today; failed attempts remain retryable."""
    return {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM actions_fetch_log "
        "WHERE fetched_on = ? AND status IN ('ok', 'empty')", [on]
    ).fetchall()}


# --------------------------------------------------------------------------- #
# collection
# --------------------------------------------------------------------------- #
def _prepare_run(con, params: dict, mode: str, on: date):
    pairs, source = _select_universe(con, params, mode)
    limit = params.get("limit")
    if limit:
        pairs = pairs[: int(limit)]
    resume = params.get("resume", True) and mode == "backfill"
    done = _already_done(con, on) if resume else set()
    pending = [(tk, yft) for tk, yft in pairs if tk not in done]
    already_done = len(done & {tk for tk, _ in pairs})
    return pairs, source, pending, already_done


def _write_checkpoint(con, action_rows: list[dict], fetch_rows: list[dict], on: date) -> int:
    """Commit action facts and their per-ticker outcomes as one recovery unit."""
    if not action_rows and not fetch_rows:
        return 0
    with db.transaction(con):
        inserted = db.upsert_actions(con, pd.DataFrame(action_rows))
        db.insert_actions_fetch_log(con, fetch_rows, fetched_on=on)
    return inserted


def _pull_pending(
    pairs: list[tuple[str, str]],
    source: str,
    pending: list[tuple[str, str]],
    already_done: int,
    on: date,
    checkpoint: Callable[[list[dict], list[dict]], int],
    count_totals: Callable[[], tuple[int, int]],
    meta_path: str | Path,
    mode: str,
) -> dict:
    """Network loop shared by persistent and connection-narrowed entry points."""
    log.info(f"[actions] mode={mode} universe={len(pairs)} source='{source}' "
          f"already_done_today={already_done} "
          f"pending={len(pending)}")

    inserted = with_actions = empty = failed = 0
    buf: list[dict] = []
    log_buf: list[dict] = []

    def _flush() -> None:
        nonlocal inserted, buf, log_buf
        if not buf and not log_buf:
            return
        inserted += checkpoint(buf, log_buf)
        buf = []
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
            log.info(f"[actions] {i}/{len(pending)} pulled (with_actions={with_actions} "
                  f"empty={empty} failed={failed} rows_written={inserted})")
        time.sleep(PER_NAME_SLEEP)
    _flush()

    totals = count_totals()
    accounting = {
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
    store_gb = rsc.live_store_gb(STORE_DIR)
    accounting["last_run"] = datetime.now(timezone.utc).isoformat()
    accounting["store_gb"] = round(store_gb, 2)
    rsc.merge_meta(meta_path, {f"actions_{mode}": accounting})
    rsc.update_disk_warning(meta_path, store_gb, snapshots_gb=rsc.snapshots_gb(STORE_DIR))
    return accounting


def collect(con, params: dict, mode: str, meta_path: str | Path = DEFAULT_META) -> dict:
    """Pull actions with retry-safe, transactionally checkpointed outcomes."""
    on = datetime.now(timezone.utc).date()
    prepared = _prepare_run(con, params, mode, on)
    return _pull_pending(
        *prepared,
        on,
        lambda action_rows, fetch_rows: _write_checkpoint(
            con, action_rows, fetch_rows, on
        ),
        lambda: con.execute(
            "SELECT COUNT(*) FILTER (WHERE kind = 'split'), "
            "COUNT(*) FILTER (WHERE kind = 'dividend') FROM corporate_actions"
        ).fetchone(),
        meta_path,
        mode,
    )


# --------------------------------------------------------------------------- #
# split reconciliation
# --------------------------------------------------------------------------- #
def _session_window(con, ticker: str,
                    ex_date: date) -> list[tuple[date, float, object, object]]:
    """Stored (date, close, fetched_at, first stored) around ex_date: SEARCH_BEFORE
    sessions before through SEARCH_AFTER sessions after, oldest first. Rows with
    a NULL close are dropped (a break can't be measured against a hole).
    fetched_at is the row's last write; the nightly 5d re-fetch restamps it on
    unchanged bars. first stored is first_fetched_at (fetched_at where it is
    NULL or the column is absent) — when the row's scale was first set. Either
    may be NULL on old copies."""
    has_first = con.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = 'prices' AND column_name = 'first_fetched_at'"
    ).fetchone()[0]
    first = "COALESCE(first_fetched_at, fetched_at)" if has_first else "fetched_at"
    before = con.execute(
        f"SELECT date, close, fetched_at, {first} FROM prices WHERE ticker = ? "
        "AND date < ? AND close IS NOT NULL ORDER BY date DESC LIMIT ?",
        [ticker, ex_date, SEARCH_BEFORE],
    ).fetchall()
    after = con.execute(
        f"SELECT date, close, fetched_at, {first} FROM prices WHERE ticker = ? "
        "AND date >= ? AND close IS NOT NULL ORDER BY date ASC LIMIT ?",
        [ticker, ex_date, SEARCH_AFTER],
    ).fetchall()
    return [(d, float(c), f, ff) for d, c, f, ff in reversed(before)] + \
           [(d, float(c), f, ff) for d, c, f, ff in after]


def _fetched_on(ts) -> date | None:
    """fetched_at -> calendar date (None when the store never stamped it)."""
    if ts is None:
        return None
    return ts.date() if isinstance(ts, datetime) else ts


def new_scale_islands(closes: list[tuple[date, float]], ratio: float) -> list[date]:
    """Dates of bars already on the post-split scale inside an old-scale run.

    An island is entered by a one-session close ratio matching `ratio` and left
    within BREAK_NEAR_EX_SESSIONS sessions by one matching its inverse. WLFC 3:1
    (ex 2026-07-21): the ex-date re-fetch stored the 07-15 bar already restated,
    the next nights' re-fetches stored its neighbours on the old scale again, and
    the July reconciler divided every bar before the 07-20 break, 07-15 included,
    putting it on a third basis (1/9 of the old scale).
    """
    lr = math.log(ratio)
    islands: list[date] = []
    start = None
    for i in range(1, len(closes)):
        prev_c, cur_c = closes[i - 1][1], closes[i][1]
        if prev_c <= 0 or cur_c <= 0:
            start = None
            continue
        lo = math.log(prev_c / cur_c)
        if abs(lo - lr) <= TOL_LOG:
            start = i
        elif start is not None and abs(lo + lr) <= TOL_LOG:
            if i - start <= BREAK_NEAR_EX_SESSIONS:
                islands += [closes[k][0] for k in range(start, i)]
            start = None
    return islands


def _adjudicate(con, ticker: str, ex_date: date, ratio: float) -> dict:
    """Decide what the STORED series says about this split. Never guesses.

    THE RULE (2026-09-02, after the BH/ORCL/NEM false breaks):
      1. Scan one-session close ratios r = close(t-1)/close(t) over the window
         SEARCH_BEFORE..SEARCH_AFTER sessions around ex_date. A candidate break
         is a session whose r matches the split ratio within TOL_LOG (±8%).
      2. LOCATION. The candidate must sit within BREAK_NEAR_EX_SESSIONS of the
         ex-date: a genuine scale break lives at the ex-date itself, or at the
         edge of the nightly 5d re-fetch just before it (module docstring). The
         one exception is a recent split (ex within RECENT_EX_SESSIONS of the
         latest bar) whose break sits later than the ex-date, i.e. the first bar
         re-fetched after a collection gap. A ratio-sized jump anywhere else is a
         real move -> `skipped_no_break_near_ex` (recorded, never restated).
      3. CONTINUITY / PROVENANCE. The bars BEFORE the candidate must have been
         FIRST stored before the ex-date (prices.first_fetched_at < ex_date,
         fetched_at where first_fetched_at is NULL). Not the last write: the
         5d re-fetch restamps fetched_at on unchanged old-scale bars, so a
         break 3-5 sessions before the ex-date always looked post-ex (ETHA
         1:3, break 10-01, ex 10-06: its 09-30 bar was restamped on the
         ex-date and the split was skipped, leaving mixed bases). Yahoo
         back-adjusts at fetch time, so bars fetched on/after the ex-date are
         already on the post-split scale and the series is already continuous
         across the split — there is nothing to restate, and the jump we found
         is either a real move or Yahoo's own unadjusted data (gh#2174). Either
         way: `skipped_already_adjusted`, hands off. (Rows with no fetched_at,
         e.g. old copies, cannot fail this check.) The one exception is a
         recorded re-fetch rewrite proving Yahoo restated late
         (`_rewrite_shows_old_scale`, module docstring).
      4. No candidate at all: a large unexplained move by the ex-date ->
         `skipped_sanity`; otherwise the store already matches the post-split
         scale -> `noop_restated`.

    A bar before the break that sits on an island of the new scale
    (`new_scale_islands`) is already restated: it is left out of rule 3 and
    returned as `new_scale_dates`, which `_restate` leaves untouched.

    Returns {outcome, break_date, observed, new_scale_dates}. Outcomes:
      applied_pending          - break located and vetted; caller restates
                                 `date < break_date`
      noop_restated            - no break: the store already matches the
                                 post-split scale
      noop_pre_history         - the split predates our earliest stored bar
      skipped_ambiguous        - |ln ratio| too small to tell the readings apart
      skipped_no_bars          - not enough stored bars around ex_date to measure
      skipped_sanity           - a large unexplained move sits by the ex-date
      skipped_no_break_near_ex - a ratio-sized jump exists in the scan window but
                                 not where a scale break can be (rule 2); the
                                 jump's date is returned as break_date for the
                                 record, rows_restated stays 0
      skipped_already_adjusted - a ratio-sized jump sits by the ex-date, but the
                                 bars before it were first stored on/after the
                                 ex-date (rule 3)
    """
    if ratio <= 0:
        return {"outcome": "skipped_sanity", "break_date": None, "observed": None}
    lr = math.log(ratio)
    if abs(lr) < MIN_SEPARATION_LOG:
        return {"outcome": "skipped_ambiguous", "break_date": None, "observed": None}

    first_bar, latest_bar = con.execute(
        "SELECT MIN(date), MAX(date) FROM prices WHERE ticker = ?", [ticker]
    ).fetchone()
    if first_bar is None:
        return {"outcome": "skipped_no_bars", "break_date": None, "observed": None}
    if first_bar >= ex_date:
        # Nothing stored before the split — there is no pre-split scale to fix.
        return {"outcome": "noop_pre_history", "break_date": None, "observed": None}

    win = _session_window(con, ticker, ex_date)
    if len(win) < 2:
        return {"outcome": "skipped_no_bars", "break_date": None, "observed": None}
    # Index of the ex session (the first stored session on/after ex_date).
    ex_idx = next((i for i, (d, *_rest) in enumerate(win) if d >= ex_date), None)
    if ex_idx is None:
        return {"outcome": "skipped_no_bars", "break_date": None, "observed": None}
    # Rule 2's exception: sessions stored on/after ex_date, up to the latest bar.
    n_after_ex = con.execute(
        "SELECT COUNT(*) FROM prices WHERE ticker = ? AND date >= ? AND date <= ?",
        [ticker, ex_date, latest_bar]).fetchone()[0]
    recent = n_after_ex <= RECENT_EX_SESSIONS

    # One-session close ratios: r[i] = close(i-1) / close(i). At the scale break
    # r == ratio (old scale over new scale), for a forward AND a reverse split.
    near = None       # (|sessions from ex|, i, break_date, observed) — rule 2 ok
    far = None        # same, for a matching jump that rule 2 rejects
    worst_move = 0.0  # largest |ln r| seen adjacent to the ex-date
    for i in range(1, len(win)):
        prev_c = win[i - 1][1]
        cur_d, cur_c = win[i][0], win[i][1]
        if prev_c <= 0 or cur_c <= 0:
            continue
        obs = prev_c / cur_c
        lo = math.log(obs)
        dist = i - ex_idx  # sessions from the ex session (negative = before)
        if abs(dist) <= 4:
            worst_move = max(worst_move, abs(lo))
        if abs(lo - lr) > TOL_LOG:
            continue
        cand = (abs(dist), i, cur_d, obs)
        ok_location = abs(dist) <= BREAK_NEAR_EX_SESSIONS or (recent and dist > 0)
        if ok_location:
            if near is None or cand[0] < near[0]:
                near = cand
        elif far is None or cand[0] < far[0]:
            far = cand

    if near is not None:
        _dist, i, break_date, obs = near
        islands = set(new_scale_islands([(d, c) for d, c, _f, _ff in win[:i]], ratio))
        old_scale = [row for row in win[:i] if row[0] not in islands]
        # Rule 3: the bars before the break must have been first stored before
        # the ex-date, unless a recorded rewrite shows they were stored on the
        # old scale.
        stored = [f for _d, _c, f, _ff in old_scale if f is not None]
        first = [_fetched_on(ff) for _d, _c, _f, ff in old_scale if ff is not None]
        if first and max(first) >= ex_date and not (
            stored and isinstance(max(stored), datetime)
            and _rewrite_shows_old_scale(con, ticker, ratio, break_date, max(stored))
        ):
            return {"outcome": "skipped_already_adjusted", "break_date": break_date,
                    "observed": obs}
        return {"outcome": "applied_pending", "break_date": break_date,
                "observed": obs, "new_scale_dates": sorted(islands)}
    if far is not None:
        return {"outcome": "skipped_no_break_near_ex", "break_date": far[2],
                "observed": far[3]}
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


def _rebuild_sim_state(con) -> None:
    """sim_positions + cash := pure function of (sim_fills, sim_dividends), on the
    post-split scale for every split watermarked 'applied'. Lives in
    sim/portfolio.py (the declared truth for --rerun); imported lazily so this
    module keeps working from the queue and from `python -m engine.actions`.
    """
    from sim import portfolio
    ids = [row[0] for row in con.execute(
        "SELECT portfolio_id FROM portfolio_accounts_v WHERE pa_engine<>'account'"
    ).fetchall()]
    portfolio.rebuild_state(con, ids)


def _restate(con, ticker: str, ex_date: date, ratio: float, break_date: date,
             keep: list[date] | tuple = ()) -> int:
    """Restate the ticker's pre-break bars to the post-split scale and adjust the
    sim books, in ONE transaction with the watermark row. Returns rows restated.

    Prices: open/high/low/close ÷ ratio, volume × ratio for `date < break_date`,
            except the `keep` dates, which are already on the post-split scale
            (`new_scale_islands`).
    Orders: pending sim_orders.qty × ratio, but only orders SIGNALLED before the
            ex-date — an order sized off a post-split close is already right.
    Sim:    positions are NOT scaled in place. The watermark row is written
            first and the books are rebuilt from sim_fills + sim_dividends via
            portfolio.rebuild_state, which scales only fills with
            fill_date < ex_date. Scaling every open position by the ratio (the
            pre-2026-09-02 behaviour) doubled any lot bought AFTER the ex-date
            and the next --rerun silently reverted it; rebuild is the one rule
            both paths now share. rebuild_state reproduced the live store's 537
            positions and every book's cash exactly before this was switched on.
    """
    keep = sorted(set(keep))
    kept = "".join(" AND date <> ?" for _ in keep)
    n = con.execute(
        f"SELECT COUNT(*) FROM prices WHERE ticker = ? AND date < ?{kept}",
        [ticker, break_date, *keep]).fetchone()[0]
    with db.transaction(con):
        previous = db.observation_rows(con.execute(
            f"SELECT * FROM prices WHERE ticker=? AND date < ?{kept}",
            [ticker, break_date, *keep],
        ))
        for bar in previous:
            candidate = {**bar, **{f: None if bar[f] is None else bar[f] / ratio
                                   for f in ("open", "high", "low", "close")},
                         "volume": None if bar["volume"] is None else round(bar["volume"] * ratio)}
            reasons = observation_reasons(candidate)
            if reasons:
                raise ValueError(f"invalid split restatement: {ticker}: {reasons}")
        db.append_price_observations(
            con, previous, reason="split_restatement_predecessor",
            batch_id=f"split:{ticker}:{ex_date}:{break_date}",
        )
        con.execute(
            "UPDATE prices SET open = open / ?, high = high / ?, low = low / ?, "
            "close = close / ?, volume = CAST(ROUND(volume * ?) AS BIGINT) "
            f"WHERE ticker = ? AND date < ?{kept}",
            [ratio, ratio, ratio, ratio, ratio, ticker, break_date, *keep],
        )
        con.execute(
            "UPDATE sim_orders SET qty = qty * ? WHERE ticker = ? "
            "AND status = 'pending' AND signal_date < ? "
            "AND portfolio_id IN (SELECT portfolio_id FROM portfolio_accounts_v "
            "WHERE pa_engine<>'account')",
            [ratio, ticker, ex_date],
        )
        con.execute(
            "INSERT OR REPLACE INTO split_adjustments (ticker, ex_date, ratio, "
            "outcome, observed, break_date, rows_restated, applied_at) "
            "VALUES (?, ?, ?, 'applied', ?, ?, ?, ?)",
            [ticker, ex_date, ratio, ratio, break_date, n,
             datetime.now(timezone.utc)],
        )
        _rebuild_sim_state(con)
        _audit(con, "split_restated", {
            "ticker": ticker, "ex_date": ex_date, "ratio": ratio,
            "break_date": break_date, "rows_restated": n,
            "positions": "rebuilt from sim_fills (fills before ex_date scaled)",
            **({"kept_on_new_scale": keep} if keep else {}),
        })
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

    Any active-book held-or-pending name whose most recent one-session close move exceeds
    TRIPWIRE_MOVE with no corporate_actions row within ±TRIPWIRE_NEAR_DAYS is a
    possible MISSED split. Returns the warning lines (also printed)."""
    names = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT p.ticker FROM sim_positions p "
            "JOIN portfolios pf ON pf.id = p.portfolio_id "
            "WHERE pf.active AND p.qty > 0 "
            "UNION SELECT DISTINCT o.ticker FROM sim_orders o "
            "JOIN portfolios pf ON pf.id = o.portfolio_id "
            "WHERE pf.active AND o.status = 'pending'"
        ).fetchall()
    ]
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
        log.info(f"[actions] {line}")
        _audit(con, "tripwire_unexplained_move",
               {"ticker": tk, "date": d, "move": move})
    return warns


def _split_sized(lr: float) -> float | None:
    """The SCAN_RATIOS ratio (or inverse) a log close ratio matches, if any.
    A move inside the ambiguity band is never split-sized (a 3:2 split's ±8%
    reaches down to ordinary -28% days)."""
    if abs(lr) < MIN_SEPARATION_LOG:
        return None
    for k in SCAN_RATIOS:
        for r in (k, 1.0 / k):
            if abs(lr - math.log(r)) <= TOL_LOG:
                return r
    return None


def _explained_by_split(con, ticker: str, day: date) -> bool:
    """A split row near `day` the reconciler has not skipped (pending or decided)."""
    return con.execute(
        "SELECT COUNT(*) FROM corporate_actions c LEFT JOIN split_adjustments s "
        "ON s.ticker = c.ticker AND s.ex_date = c.ex_date "
        "WHERE c.ticker = ? AND c.kind = 'split' AND c.ex_date BETWEEN ? AND ? "
        "AND (s.outcome IS NULL OR s.outcome NOT LIKE 'skipped%')",
        [ticker, day - timedelta(days=TRIPWIRE_NEAR_DAYS),
         day + timedelta(days=TRIPWIRE_NEAR_DAYS)],
    ).fetchone()[0] > 0


def scan_breaks(con, sessions: int = SCAN_SESSIONS) -> list[str]:
    """Guard (b), wide pass: the last `sessions` sessions of every liquid name
    (plus held and pending names), independent of what the actions feed says.

    Two shapes are flagged and quarantined (buys refused until a human resolves):
      * a split-ratio break: close(t-1)/close(t) within TOL_LOG of a SCAN_RATIOS
        ratio or its inverse, the median volume of the VOLUME_SESSIONS bars after
        it shifted by that ratio (within half its log size) against the bars
        before, and no split row nearby that the reconciler has not skipped;
      * a split-sized single-bar glitch: a move of at least the ambiguity band
        that the next bar reverses within TOL_LOG (MNST, RUSHA).
    A name with an active quarantine keeps it; one a human resolved on or after
    the flagged session is not re-flagged."""
    if not table_exists(con, "universe"):
        return []
    days = con.execute(
        "SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT ?",
        [sessions + VOLUME_SESSIONS],
    ).fetchall()
    if len(days) < 2:
        return []
    scan_from = days[min(sessions, len(days)) - 1][0]
    rows = con.execute(
        "SELECT ticker, date, close, volume FROM prices WHERE date >= ? AND close > 0 "
        "AND ticker IN (SELECT ticker FROM universe WHERE liquid "
        "UNION SELECT p.ticker FROM sim_positions p JOIN portfolios pf "
        "ON pf.id = p.portfolio_id WHERE pf.active AND p.qty > 0 "
        "UNION SELECT o.ticker FROM sim_orders o JOIN portfolios pf "
        "ON pf.id = o.portfolio_id WHERE pf.active AND o.status = 'pending') "
        "ORDER BY ticker, date",
        [days[-1][0]],
    ).fetchall()
    series: dict[str, list[tuple[date, float, float]]] = {}
    for tk, d, c, v in rows:
        series.setdefault(tk, []).append((d, float(c), float(v or 0)))

    flags: list[tuple[str, date, str, dict]] = []
    for tk, s in series.items():
        i = 1
        while i < len(s):
            d, c = s[i][0], s[i][1]
            lr = math.log(s[i - 1][1] / c)
            if d < scan_from:
                i += 1
                continue
            if (abs(lr) >= MIN_SEPARATION_LOG and i + 1 < len(s)
                    and abs(lr + math.log(c / s[i + 1][1])) <= TOL_LOG):
                flags.append((tk, d, QUARANTINE_GLITCH, {
                    "date": d.isoformat(), "prev_close": s[i - 1][1], "close": c,
                    "next_close": s[i + 1][1]}))
                i += 2      # the reversing bar is the glitch's other half
                continue
            ratio = _split_sized(lr)
            pre = [v for _d, _c, v in s[max(0, i - VOLUME_SESSIONS):i] if v > 0]
            post = [v for _d, _c, v in s[i:i + VOLUME_SESSIONS] if v > 0]
            if ratio is not None and pre and post:
                shift = math.log(statistics.median(post) / statistics.median(pre))
                if (abs(shift - math.log(ratio)) <= abs(math.log(ratio)) / 2
                        and not _explained_by_split(con, tk, d)):
                    flags.append((tk, d, QUARANTINE_SPLIT, {
                        "date": d.isoformat(), "prev_close": s[i - 1][1], "close": c,
                        "ratio": ratio, "volume_shift": math.exp(shift)}))
            i += 1

    from engine import price_quarantine
    warns: list[str] = []
    for tk, d, reason, evidence in flags:
        row = con.execute(
            "SELECT status, resolved_at FROM price_quarantine WHERE ticker = ?", [tk]
        ).fetchone()
        active = row is not None and row[0] == "active"
        if not active and row is not None and row[1] is not None \
                and _fetched_on(row[1]) >= d:
            continue    # a human resolved this name after the flagged session
        line = (f"WARN break scan: {tk} {reason} on {d} (close {evidence['prev_close']:g}"
                f" -> {evidence['close']:g}) — quarantined, needs a human")
        warns.append(line)
        log.info(f"[actions] {line}")
        if not active:
            price_quarantine.set_quarantine(
                con, tk, reason=reason, evidence=json.dumps(evidence, sort_keys=True))
    return warns


def _resolve_split_quarantine(con, ticker: str, ex_date: date) -> None:
    """A split the reconciler just restated clears the break scan's quarantine."""
    if not table_exists(con, "price_quarantine"):
        return
    row = con.execute(
        "SELECT reason FROM price_quarantine WHERE ticker = ? AND status = 'active'",
        [ticker]).fetchone()
    if row is not None and row[0] == QUARANTINE_SPLIT:
        from engine import price_quarantine
        price_quarantine.resolve_quarantine(
            con, ticker, resolution=f"split ex {ex_date} restated by actions.reconcile")


def reconcile(con) -> dict:
    """Adjudicate every not-yet-considered split with ex_date <= the latest bar,
    restating where the stored series genuinely shows the break. Idempotent: the
    split_adjustments watermark means each split is decided exactly once."""
    latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if latest is None:
        log.info("[actions] reconcile: prices table is empty; nothing to do")
        return {"candidates": 0}

    cands = con.execute(
        "SELECT c.ticker, c.ex_date, c.value FROM corporate_actions c "
        "LEFT JOIN split_adjustments s ON s.ticker = c.ticker AND s.ex_date = c.ex_date "
        "WHERE c.kind = 'split' AND c.ex_date <= ? AND s.ticker IS NULL "
        "ORDER BY c.ex_date, c.ticker",
        [latest],
    ).fetchall()
    log.info(f"[actions] reconcile: {len(cands)} unadjudicated split(s) "
          f"with ex_date <= {latest}")

    counts: dict[str, int] = {}
    restated_rows = 0
    todos: list[str] = []
    for tk, ex, ratio in cands:
        ratio = float(ratio)
        v = _adjudicate(con, tk, ex, ratio)
        outcome = v["outcome"]
        if outcome == "applied_pending":
            n = _restate(con, tk, ex, ratio, v["break_date"],
                         keep=v.get("new_scale_dates", ()))
            _resolve_split_quarantine(con, tk, ex)
            restated_rows += n
            outcome = "applied"
            log.info(f"[actions] RESTATED {tk} split {ratio:g}:1 ex={ex} "
                  f"break={v['break_date']} rows={n} (obs {v['observed']:.4f}) "
                  f"— pre-ex pending orders rescaled, positions rebuilt from fills")
        else:
            _mark(con, tk, ex, ratio, v)
            if outcome.startswith("skipped"):
                line = (f"WARN {outcome}: {tk} split {ratio:g}:1 ex={ex} "
                        f"(observed {v['observed']}) — NOT restated, needs a human")
                todos.append(line)
                log.info(f"[actions] {line}")
                _audit(con, f"split_{outcome}",
                       {"ticker": tk, "ex_date": ex, "ratio": ratio,
                        "observed": v["observed"]})
        counts[outcome] = counts.get(outcome, 0) + 1

    todos += tripwire(con)
    todos += scan_breaks(con)
    todos += _unexplained_rewrites(con)
    summary = {"candidates": len(cands), "rows_restated": restated_rows,
               "outcomes": counts, "warnings": len(todos)}
    log.info(f"[actions] reconcile DONE: {counts or '{}'} rows_restated={restated_rows}")
    if todos:
        # The first reconcile after a full backfill adjudicates the entire split
        # history of ~12k names at once, so the never-guess skips arrive as a
        # one-time burst. Cap the nightly log; audit_log has every one of them.
        log.error(f"TODO: corporate actions need review ({len(todos)}):")
        for t in todos[:TODO_LOG_CAP]:
            log.error(f"TODO:   {t}")
        if len(todos) > TODO_LOG_CAP:
            log.error(f"TODO:   … and {len(todos) - TODO_LOG_CAP} more — full list in "
                  f"audit_log (actor='actions.reconcile')")
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
    from sim.schema import init_sim_schema
    init_sim_schema(con)
    mode = params.get("mode", "backfill")

    if mode == "reconcile":
        acc = reconcile(con)
        store_gb = rsc.live_store_gb(STORE_DIR)
        acc["last_run"] = datetime.now(timezone.utc).isoformat()
        acc["store_gb"] = round(store_gb, 2)
        rsc.merge_meta(meta_path, {f"actions_{mode}": acc})
        rsc.update_disk_warning(meta_path, store_gb, snapshots_gb=rsc.snapshots_gb(STORE_DIR))
    else:
        acc = collect(con, params, mode, meta_path=meta_path)
        if params.get("reconcile", False):
            acc["reconcile"] = reconcile(con)
            rsc.merge_meta(meta_path, {f"actions_{mode}": acc})
    return acc


def run_connection_narrowed(
    params: dict | None,
    db_path: str | Path | None = None,
    meta_path: str | Path = DEFAULT_META,
) -> dict:
    """Collect actions without holding DuckDB through per-name HTTP waits."""
    params = params or {}
    mode = params.get("mode", "backfill")
    if mode == "reconcile":
        con = db.connect(db_path) if db_path is not None else db.connect()
        try:
            db.init_schema(con)
            db.init_queue_schema(con)
            return run(params, con, meta_path=meta_path)
        finally:
            con.close()

    path = Path(db_path) if db_path is not None else db.DEFAULT_DB
    on = datetime.now(timezone.utc).date()
    con = db.connect(path)
    try:
        db.init_schema(con)
        db.init_queue_schema(con)
        db.init_actions_schema(con)
        from sim.schema import init_sim_schema
        init_sim_schema(con)
        prepared = _prepare_run(con, params, mode, on)
    finally:
        con.close()

    def checkpoint(action_rows: list[dict], fetch_rows: list[dict]) -> int:
        write_con = db.connect(path)
        try:
            return _write_checkpoint(write_con, action_rows, fetch_rows, on)
        finally:
            write_con.close()

    def count_totals() -> tuple[int, int]:
        read_con = db.connect(path, read_only=True)
        try:
            return read_con.execute(
                "SELECT COUNT(*) FILTER (WHERE kind = 'split'), "
                "COUNT(*) FILTER (WHERE kind = 'dividend') FROM corporate_actions"
            ).fetchone()
        finally:
            read_con.close()

    acc = _pull_pending(
        *prepared, on, checkpoint, count_totals, meta_path, mode
    )
    if params.get("reconcile", False):
        write_con = db.connect(path)
        try:
            acc["reconcile"] = reconcile(write_con)
        finally:
            write_con.close()
        rsc.merge_meta(meta_path, {f"actions_{mode}": acc})
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
    ap.add_argument("--rolling-slices", type=int, default=ROLLING_SLICES,
                    help="incremental also pulls 1/N of the liquid universe (0 = off)")
    args = ap.parse_args()

    params: dict = {"mode": args.mode, "top_n": args.top_n,
                    "resume": not args.no_resume,
                    "rolling_slices": args.rolling_slices}
    if args.tickers:
        params["tickers"] = args.tickers
    if args.limit:
        params["limit"] = args.limit

    if args.mode == "reconcile":
        con = db.connect(args.db) if args.db else db.connect()
        try:
            db.init_schema(con)
            db.init_queue_schema(con)
            run(params, con, meta_path=args.meta)
        finally:
            con.close()
    else:
        run_connection_narrowed(params, db_path=args.db, meta_path=args.meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
