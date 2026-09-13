#!/usr/bin/env python
"""Replay ONE league book over ONE historical window — the farm's unit of work.

The honesty rule of this module: **nothing about a strategy is reimplemented
here.** A replay builds a scratch store, creates the book's portfolio row with
`sim/league.py.init_portfolios`, injects a point-in-time screen, and then calls
`sim/league.py.step()` once per session. Orders come from the real strategy
classes, fills from the real `sim/fills.py` (t+1 open, slippage tiers, liquidity
guard, no same-bar fills, never an invented bar), dividends from the real phase
a0. This is `sim/backtest_shakedown.py`'s shape, extended from 25 sessions to
15 years and narrowed to one book per job so the grid parallelizes across the
queue.

Scratch, not the live store. The live connection is used for SELECTs and
`COPY … TO 'x.parquet'` only — it is never written. Every replay write lands in
`scratch/<config_id>__<window>/replay.duckdb`, which the job deletes when it
finishes (--keep-scratch to inspect one). The scratch store is SLIM on purpose:

  prices            date ∈ [start − 460 sessions, end]  (all tickers)
  corporate_actions ex_date ≤ end                        (dividend crediting)
  universe          full copy (`high_52wk` / `low_vol` read active/liquid/etf)
  fundamentals      the latest snapshot, RESTAMPED to the warmup start
  screen_results    hist_screen output for the window's sessions (passing rows)
  sim_* tables      empty; exactly one portfolio row

460 sessions of price warmup covers every lookback any book reads: the screen's
400-bar pull, the 252-session total returns, `high_52wk`'s 430-calendar-day
window, `low_vol`'s 428-day vol window, the 200-session SPY regime and the
60-bar median-dollar-volume the fill model prices slippage from.

Two documented data compromises, both disclosed in every report:
  * `fundamentals` has no history (first snapshot 2026-07-18), so `low_vol`'s
    "market cap ≥ $5B" filter is TODAY's cap list restamped to the window start.
    Static-cap look-ahead. Without it `low_vol` is simply inert historically,
    which would be a silent non-result rather than a disclosed approximation.
  * `universe.active/liquid/etf` are today's flags (the membership snapshots
    only start 2026-07-16), so `high_52wk`/`low_vol` candidate sets are the
    survivor universe. Same survivorship as `prices` itself.

Window ends are all 2026-07-16 — the session before league inception — so the
forward record stays strictly out of sample relative to this farm.

Entry points:
    CLI:   farm/backtest/replay.py --config template_top5 --window 6mo
    Queue: run_job(params, con, meta_path=None) — job kind 'backtest',
           params {"config_id": …, "window": …}
"""
from __future__ import annotations

import argparse
import calendar as _cal
import json
import shutil
import time
from datetime import date
from pathlib import Path

from engine.lib import db, resources
from engine.lib import leverage as lev
from engine.lib.data_quality import data_snapshot, quality_class
from engine.lib.log import get_logger
from engine.lib.provenance import research_provenance
from engine.lib.settings import DATA_DIR, REPO_ROOT
from engine.lib.util import num, table_exists
from farm.backtest import hist_screen, stats
from sim import execution, league
from sim import portfolio as _pf
from sim.schema import INITIAL_CASH, init_sim_schema
from sim.strategies.configs import CONFIGS, config_by_id

log = get_logger("replay")

SCRATCH_ROOT = REPO_ROOT / "scratch"
RESULTS_DIR = DATA_DIR / "reports" / "backtests" / "results"

# Every window ends the session before league inception (2026-07-17), so the
# farm's evidence and the live forward record never overlap.
WINDOW_END = date(2026, 7, 16)
WINDOW_MONTHS: dict[str, int | None] = {
    "6mo": 6, "1y": 12, "3y": 36, "5y": 60, "15y": 180, "max": None,
}

PRICE_WARMUP_SESSIONS = 460   # covers every lookback any book reads (see above)


def _provenance(config: dict) -> dict:
    return research_provenance(config)


def _require_single_portfolio(con) -> None:
    """Reject replay scratch state that is missing or mixes portfolio books."""
    count = con.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0]
    if count != 1:
        raise RuntimeError(
            "replay scratch database must contain exactly one portfolio; "
            f"found {count}"
        )


# Books excluded from the farm, with the reason printed in every report.
EXCLUDED = {
    "pead_ear": "no historical earnings dates — earnings_calendar spans only "
                "2026-04→2026-10, so the entry signal cannot be computed. "
                "Forward record only.",
    "discretionary": "human book — orders come from UI tickets, not code.",
    "macro_composite": "historical point-in-time macro inputs do not exist; "
                       "replaying an empty macro_signals table would synthesize "
                       "a neutral allocation rather than test the registered rule.",
}
EXCLUDED_STRATEGIES = {
    "pead_ear": EXCLUDED["pead_ear"],
    "discretionary": EXCLUDED["discretionary"],
    "macro_composite": EXCLUDED["macro_composite"],
}


def excluded_reason(config_id: str, strategy: str | None = None) -> str | None:
    """Return why an ID or any config using its strategy cannot be replayed."""
    if config_id in EXCLUDED:
        return EXCLUDED[config_id]
    if strategy in EXCLUDED_STRATEGIES:
        return f"{EXCLUDED_STRATEGIES[strategy]} (excluded via strategy `{strategy}`)"
    return None


def registered_config(live_con, config_id: str) -> dict:
    """Return the frozen live portfolio config, falling back before init."""
    source = config_by_id(config_id)
    row = live_con.execute(
        "SELECT config, active FROM portfolios WHERE id = ?", [config_id]
    ).fetchone()
    if row is None:
        return source
    if not row[1]:
        raise SystemExit(f"[replay] {config_id} is retired (active=false)")
    try:
        frozen = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[replay] {config_id} has invalid frozen config: {exc}") from exc
    if frozen.get("id") != config_id or not frozen.get("strategy"):
        raise SystemExit(f"[replay] {config_id} has an inconsistent frozen config")
    return frozen


def registered_assumptions(live_con, config_id: str) -> tuple[float, str]:
    """Persisted capital/profile for a live book, or compatibility defaults."""
    columns = {r[1] for r in live_con.execute(
        "PRAGMA table_info('portfolios')").fetchall()}
    if "initial_cash" not in columns or "execution_profile" not in columns:
        return INITIAL_CASH, execution.DEFAULT_PROFILE_ID
    row = live_con.execute(
        "SELECT COALESCE(initial_cash, ?), COALESCE(execution_profile, ?) "
        "FROM portfolios WHERE id = ?",
        [INITIAL_CASH, execution.DEFAULT_PROFILE_ID, config_id],
    ).fetchone()
    if row is None:
        return INITIAL_CASH, execution.DEFAULT_PROFILE_ID
    return float(row[0]), str(row[1])

# Books that read `screen_results` (everything else skips the screen build).
NEEDS_SCREEN = {"template_top5", "template_top10_banded", "mr_overlay",
                "momo_stopped", "turtle_breakout", "ew_benchmark",
                # Both 2026-08-18 drawdown probes trade the ew_benchmark basket,
                # so they need the screen for exactly the same reason it does.
                # Omitting them here does NOT error -- `latest_screen_date`
                # simply returns None and the book silently posts zero orders,
                # which is how the first walk-forward of ew_voltarget came back
                # "0 fills, +0.00%" instead of failing loudly.
                "ew_voltarget", "ew_trend_gated",
                # The 2026-08-20 gross-exposure / sector / drawdown
                # candidates trade the same ew_benchmark basket, so they
                # need the screen for the same reason it does. Omitting a
                # strategy here does NOT error: latest_screen_date returns
                # None and the book posts ZERO orders, silently, forever.
                "ew_gross_voltarget", "ew_sector_capped",
                "ew_static_exposure",
                "ew_dd_throttle"}

# Tickers a book cannot start without, each needing 252 sessions of lookback.
# XLC (2018-06) is deliberately absent from sector_momentum's list: the strategy
# skips a sector with insufficient history rather than scoring it short, so its
# late listing is handled by the strategy, not by clamping the whole window.
REQUIRED: dict[str, list[str]] = {
    "spy_benchmark": ["SPY"],
    "dual_momentum": ["SPY", "EFA", "BIL"],
    "sector_momentum": ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU",
                        "XLB", "XLRE"],
    "fixed_etf_buy_hold": ["SPY", "IEF", "GLD"],
    "fixed_etf_rebalanced": ["SPY", "IEF", "GLD"],
    # BIL is where the book actually sits whenever SPY is below its 200d, so it
    # is as load-bearing as SPY here and its 2007-05 listing must clamp the
    # window floor rather than silently producing un-funded risk-off stretches.
    "ew_trend_gated": ["SPY", "BIL"],
    # Both rotate their de-risked fraction into BIL, so BIL is as
    # load-bearing as SPY and its 2007-05 listing must clamp the window
    # floor rather than producing un-funded risk-off stretches.
    # ew_sector_capped is deliberately ABSENT: it never touches BIL, it
    # is 100% invested in screen names at all times, so clamping its
    # floor to BIL would cost it folds for no reason.
    "ew_gross_voltarget": ["SPY", "BIL"],
    "ew_static_exposure": ["SPY", "BIL"],
    "ew_dd_throttle": ["SPY", "BIL"],
    # 2026-09-02: every slot of the sleeve can sit in BIL, and DBC (2006-02) is
    # the youngest risk asset; a window opening before either would replay a
    # book with un-funded slots rather than the book as registered.
    "multi_asset_trend": ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC",
                          "VNQ", "BIL"],
}
DEFAULT_REQUIRED = ["SPY"]     # SPY-200d regime + the report's vs-SPY column
REQUIRED_LOOKBACK = 252


# --------------------------------------------------------------------------- #
# window resolution
# --------------------------------------------------------------------------- #
def _minus_months(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


def data_floor(con, config_id: str) -> date:
    """Earliest session at which this book's required tickers all have 253 bars."""
    cfg = config_by_id(config_id)
    floors = []
    for tk in REQUIRED.get(cfg["strategy"], DEFAULT_REQUIRED):
        row = con.execute(
            "SELECT date FROM prices WHERE ticker = ? ORDER BY date "
            "LIMIT 1 OFFSET ?", [tk, REQUIRED_LOOKBACK]).fetchone()
        if row is None:
            raise SystemExit(f"[replay] {config_id}: required ticker {tk} has "
                             f"fewer than {REQUIRED_LOOKBACK + 1} bars")
        floors.append(row[0])
    return max(floors)


def resolve_window(con, config_id: str, window: str,
                   override: tuple[date, date] | None = None
                   ) -> tuple[date, date, bool]:
    """(start, end, clamped) — the first/last session actually replayed."""
    if override is not None:
        a, b = override
        start = con.execute(
            "SELECT MIN(date) FROM prices WHERE date >= ?", [a]).fetchone()[0]
        end = con.execute(
            "SELECT MAX(date) FROM prices WHERE date <= ?", [b]).fetchone()[0]
        return start, end, False
    if window not in WINDOW_MONTHS:
        raise SystemExit(f"[replay] unknown window {window!r} "
                         f"(known: {', '.join(WINDOW_MONTHS)})")
    months = WINDOW_MONTHS[window]
    floor = data_floor(con, config_id)
    target = floor if months is None else _minus_months(WINDOW_END, months)
    clamped = target < floor
    want = max(target, floor)
    start = con.execute(
        "SELECT MIN(date) FROM prices WHERE date >= ?", [want]).fetchone()[0]
    end = con.execute(
        "SELECT MAX(date) FROM prices WHERE date <= ?", [WINDOW_END]).fetchone()[0]
    if start is None or end is None or start >= end:
        raise SystemExit(f"[replay] {config_id}/{window}: empty window")
    return start, end, clamped


# --------------------------------------------------------------------------- #
# scratch store
# --------------------------------------------------------------------------- #
def build_scratch(live_con, scratch_dir: Path, start: date, end: date,
                  verbose: bool = True) -> Path:
    """Materialize the slim scratch store. `live_con` is only READ from."""
    t0 = time.time()
    scratch_dir.mkdir(parents=True, exist_ok=True)
    px_start = hist_screen.session_n_back(live_con, start, PRICE_WARMUP_SESSIONS)

    pq = scratch_dir / "_export"
    pq.mkdir(exist_ok=True)
    exports = {
        "prices": ("SELECT * FROM prices WHERE date >= ? AND date <= ?",
                   [px_start, end]),
        "corporate_actions": ("SELECT * FROM corporate_actions WHERE ex_date <= ?",
                              [end]),
        "universe": ("SELECT * FROM universe", []),
        "fundamentals": ("SELECT * FROM fundamentals WHERE as_of = "
                         "(SELECT MAX(as_of) FROM fundamentals)", []),
    }
    for name, (sql, params) in exports.items():
        live_con.execute(
            f"COPY ({sql}) TO '{pq / name}.parquet' (FORMAT PARQUET)", params)

    path = scratch_dir / "replay.duckdb"
    if path.exists():
        path.unlink()
    con = db.connect(path)
    try:
        db.init_schema(con)
        db.init_queue_schema(con)
        db.init_mining_schema(con)
        db.init_actions_schema(con)
        init_sim_schema(con)
        for name in exports:
            con.execute(f"INSERT INTO {name} SELECT * FROM '{pq / name}.parquet'")
        if table_exists(live_con, "price_quarantine"):
            quarantines = live_con.execute(
                "SELECT ticker, status, reason, evidence, confirmed_at, resolved_at, "
                "resolution FROM price_quarantine").fetchall()
            if quarantines:
                con.executemany(
                    "INSERT INTO price_quarantine VALUES (?, ?, ?, ?, ?, ?, ?)",
                    quarantines)
        # Restamp the fundamentals snapshot so low_vol's cap filter resolves at every
        # replay date (`f.as_of = (SELECT MAX(as_of) … WHERE as_of <= d)`). This is
        # the disclosed static-cap look-ahead; see the module docstring.
        con.execute("UPDATE fundamentals SET as_of = ?", [px_start])
        n_px = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        n_ca = con.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
    finally:
        con.close()
    shutil.rmtree(pq, ignore_errors=True)
    if verbose:
        log.info(f"[replay] scratch {path} built in {time.time() - t0:.0f}s "
              f"(prices {n_px:,} rows from {px_start}, actions {n_ca:,})")
    return path


def _copy_live_screens(live_con, con, start: date, end: date) -> int:
    """screen_source='m1': lift the live screen rows that already exist."""
    df = live_con.execute(
        "SELECT * FROM screen_results WHERE run_date >= ? AND run_date <= ?",
        [start, end]).fetch_df()
    if df.empty:
        return 0
    with db.registered_frame(con, "_live_sr", df):
        con.execute("INSERT INTO screen_results SELECT * FROM _live_sr")
    return len(df)


def _run_m1_screens(db_path: Path, sessions: list[date], data_dir: Path) -> None:
    """screen_source='m1': run the real M1 screener for any missing session."""
    from engine import screen as m1_screen

    con = db.connect(db_path)
    try:
        have = {r[0] for r in con.execute(
            "SELECT DISTINCT run_date FROM screen_results").fetchall()}
    finally:
        con.close()
    todo = [d for d in sessions if d not in have]
    log.info(f"[replay] m1 screens: {len(todo)} of {len(sessions)} sessions missing")
    for d in todo:
        m1_screen.run(str(db_path), data_dir, d.isoformat(), rerun=False)


# --------------------------------------------------------------------------- #
# the replay
# --------------------------------------------------------------------------- #
def run_replay(live_con, config_id: str, window: str, *,
               scratch_root: Path = SCRATCH_ROOT, screen_source: str = "hist",
               keep_scratch: bool = False, results_dir: Path = RESULTS_DIR,
               write_result: bool = True, verbose: bool = True,
               threads: int | None = 16, mem_mb: int | None = 8000,
               override: tuple[date, date] | None = None,
               initial_cash: float | None = None,
               execution_profile: str | None = None) -> dict:
    """Replay one (book, window). Returns the result dict (also written as JSON)."""
    source_cfg = config_by_id(config_id)
    why = excluded_reason(config_id, source_cfg.get("strategy"))
    if why:
        raise SystemExit(f"[replay] {config_id} is excluded: {why}")
    if not source_cfg.get("active", True):
        raise SystemExit(f"[replay] {config_id} is retired (active=false)")
    registered_cash, registered_profile = registered_assumptions(
        live_con, config_id)
    initial_cash = float(registered_cash if initial_cash is None else initial_cash)
    if not initial_cash > 0:
        raise ValueError("initial_cash must be positive")
    profile = execution.resolve_profile(execution_profile or registered_profile)
    cfg = registered_config(live_con, config_id)
    # Freeze before any historical work starts. A replay can run for hours;
    # stamping at write time could describe source edited after this process
    # imported and began executing it.
    run_provenance = _provenance(cfg)
    run_data_snapshot = data_snapshot(live_con)
    start, end, clamped = resolve_window(live_con, config_id, window, override)
    sessions = hist_screen.sessions_between(live_con, start, end)
    t0 = time.time()
    log.info(f"[replay] {config_id} / {window}: {len(sessions)} sessions "
          f"{start} → {end}{' (CLAMPED to data floor)' if clamped else ''}")

    scratch_dir = Path(scratch_root) / f"{config_id}__{window}"
    shutil.rmtree(scratch_dir, ignore_errors=True)
    result: dict = {}
    con = None
    try:
        db_path = build_scratch(live_con, scratch_dir, start, end, verbose=verbose)
        con = db.connect(db_path)
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        # Honour the job's DECLARED memory (queue_runner budgets 8 GB for a
        # backtest). Without this DuckDB would help itself to ~80% of the box's
        # 62 GiB, which is fine for one interactive run and wrong for 78 jobs
        # draining unattended next to the nightly. DuckDB spills to disk past
        # the limit — slower, never an OOM.
        if mem_mb:
            con.execute(f"SET memory_limit = '{int(mem_mb)}MB'")
        con.execute(f"SET temp_directory = '{scratch_dir}'")

        t_screen = time.time()
        n_screen = 0
        # Resolved once per replay and RECORDED in the result JSON below. A
        # result whose screen policy is unknown cannot be compared to any other
        # result, so the policy travels with the number, not with the operator's
        # memory of how the job was launched.
        policy = lev.resolve_policy(None)
        if cfg["strategy"] in NEEDS_SCREEN:
            if screen_source == "hist":
                n_screen = hist_screen.screen_sessions(
                    con, sessions, membership="prices", passing_only=True,
                    universe_policy=policy, verbose=verbose)
            elif screen_source == "m1":
                n_screen = _copy_live_screens(live_con, con, start, end)
                con.close()
                con = None
                _run_m1_screens(db_path, sessions, scratch_dir / "screens")
                con = db.connect(db_path)
                n_screen = con.execute(
                    "SELECT COUNT(*) FROM screen_results").fetchone()[0]
            else:
                raise SystemExit(f"[replay] bad screen_source {screen_source!r}")
        screen_s = time.time() - t_screen

        # Portfolio: insert the frozen live config selected above. Calling
        # init_portfolios here would silently substitute mutable source CONFIGS
        # and could replay a different rule under the same ID.
        con.execute(
            "INSERT INTO portfolios (id, name, strategy, config, created, active, "
            "cash, initial_cash, execution_profile) "
            "VALUES (?, ?, ?, ?, ?, TRUE, ?, ?, ?)",
            [config_id, cfg["name"], cfg["strategy"], json.dumps(cfg), start,
             initial_cash, initial_cash, profile.id],
        )
        _require_single_portfolio(con)

        t_step = time.time()
        for i, d in enumerate(sessions):
            league.step(con, d, scratch_dir, rerun=False, verbose=False)
            if verbose and (i + 1) % 250 == 0:
                log.info(f"[replay]   {i + 1}/{len(sessions)} sessions "
                      f"({time.time() - t_step:.0f}s)")
        step_s = time.time() - t_step

        eq = con.execute(
            "SELECT date, equity FROM sim_equity WHERE portfolio_id = ? "
            "ORDER BY date", [config_id]).fetchall()
        bil = stats.bil_daily_returns(con, start, end)
        st = stats.equity_stats(
            [r[0] for r in eq], [r[1] for r in eq], bil, initial_cash)
        n_fills = con.execute(
            "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ?",
            [config_id]).fetchone()[0]
        n_rej = con.execute(
            "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ? AND "
            "status = 'rejected'", [config_id]).fetchone()[0]
        capacity = con.execute(
            "SELECT COUNT(*) FILTER (WHERE a.outcome = 'rejected' AND "
            "a.reject_reason LIKE 'illiquid:%'), "
            "COALESCE(SUM(a.raw_notional) FILTER (WHERE a.outcome = 'rejected' "
            "AND a.reject_reason LIKE 'illiquid:%'), 0) "
            "FROM sim_execution_attempts a JOIN sim_orders o ON o.id = a.order_id "
            "WHERE o.portfolio_id = ?", [config_id]).fetchone()
        costs = con.execute(
            "SELECT COALESCE(SUM(ABS(f.qty * f.open_px)), 0), "
            "COALESCE(SUM(ABS(f.qty * f.open_px) * c.market_bps / 10000), 0), "
            "COALESCE(SUM(ABS(f.qty * f.open_px) * c.total_bps / 10000), 0), "
            "COALESCE(QUANTILE_CONT(c.participation, 0.95), 0), "
            "COALESCE(MAX(c.participation), 0) "
            "FROM sim_fills f LEFT JOIN sim_fill_costs c USING (order_id) "
            "WHERE f.portfolio_id = ?", [config_id]).fetchone()
        n_div = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM sim_dividends "
            "WHERE portfolio_id = ?", [config_id]).fetchone()
        n_actions = con.execute(
            "SELECT COUNT(*) FROM corporate_actions WHERE kind = 'dividend'"
        ).fetchone()[0]
        monthly = con.execute(
            "SELECT strftime(date, '%Y-%m') AS m, LAST(equity ORDER BY date) "
            "FROM sim_equity WHERE portfolio_id = ? GROUP BY m ORDER BY m",
            [config_id]).fetchall()

        result = {
            "config_id": config_id,
            "fill_model": _pf.FILL_MODEL_VERSION,
            "initial_cash": initial_cash,
            "execution_profile": profile.as_dict(),
            "data_quality_class": quality_class(cfg["strategy"]),
            "data_snapshot": run_data_snapshot,
            "name": cfg["name"],
            "strategy": cfg["strategy"],
            "cadence": cfg["cadence"],
            "window": window,
            "window_end_target": WINDOW_END.isoformat(),
            "clamped_to_data_floor": clamped,
            "screen_source": screen_source if cfg["strategy"] in NEEDS_SCREEN
                             else "not-used",
            "screen_rows": n_screen,
            "universe_policy": policy,
            **run_provenance,
            "n_fills": n_fills,
            "n_rejected": n_rej,
            "n_capacity_rejected": int(capacity[0]),
            "capacity_rejected_notional": float(capacity[1]),
            "p95_participation": float(costs[3]),
            "max_participation": float(costs[4]),
            "gross_traded_notional": float(costs[0]),
            "turnover_on_initial_cash": float(costs[0]) / initial_cash,
            "modeled_price_cost_dollars": float(costs[1]),
            "modeled_total_cost_dollars": float(costs[2]),
            "n_dividend_credits": n_div[0],
            "dividend_cash": float(n_div[1]),
            "corporate_actions_dividend_rows": n_actions,
            "runtime_s": round(time.time() - t0, 1),
            "screen_s": round(screen_s, 1),
            "step_s": round(step_s, 1),
            "monthly_equity": [[m, float(e)] for m, e in monthly],
            **st,
        }
        if write_result:
            results_dir.mkdir(parents=True, exist_ok=True)
            out = results_dir / f"{config_id}__{window}.json"
            resources.write_text_atomic(
                out, json.dumps(result, indent=2, sort_keys=True) + "\n"
            )
            log.info(f"[replay] wrote {out}")
    finally:
        try:
            if con is not None:
                con.close()
        finally:
            if not keep_scratch:
                shutil.rmtree(scratch_dir, ignore_errors=True)

    log.info(f"[replay] {config_id}/{window} done in {result.get('runtime_s')}s: "
          f"CAGR {_pct(result.get('cagr'))} vol {_pct(result.get('vol_ann'))} "
          f"Sharpe {num(result.get('sharpe'))} maxDD {_pct(result.get('max_dd'))} "
          f"fills {result.get('n_fills')}")
    return result


def _pct(v) -> str:
    return "·" if v is None else f"{v * 100:+.2f}%"


# --------------------------------------------------------------------------- #
# queue entry point
# --------------------------------------------------------------------------- #
def run_job(params: dict, con, meta_path=None) -> None:
    """Queue dispatch (job kind 'backtest'), params {config_id, window}.

    `con` is the runner's LIVE connection. It is used read-only here (SELECTs
    plus COPY … TO parquet); every write goes to the job's scratch store.
    """
    cfg_id = params.get("config_id")
    window = params.get("window", "1y")
    if not cfg_id:
        raise ValueError("backtest job needs params {'config_id': …, 'window': …}")
    run_replay(con, cfg_id, window,
               screen_source=params.get("screen_source", "hist"),
               mem_mb=params.get("mem_mb", 4500),
               initial_cash=(float(params["initial_cash"])
                             if "initial_cash" in params else None),
               execution_profile=params.get("execution_profile"))
    from farm.backtest import report
    report.write_reports()


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Replay one league book over one window.")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="LIVE store (read-only)")
    ap.add_argument("--config", required=True, help="config id, or 'list'")
    ap.add_argument("--window", default="6mo", choices=list(WINDOW_MONTHS))
    ap.add_argument("--screen-source", default="hist", choices=["hist", "m1"])
    ap.add_argument("--scratch-root", default=str(SCRATCH_ROOT))
    ap.add_argument("--keep-scratch", action="store_true")
    ap.add_argument("--no-result", action="store_true", help="don't write the JSON")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--initial-cash", type=float, default=None,
                    help="override the portfolio's persisted starting capital")
    ap.add_argument("--execution-profile", default=None,
                    choices=list(execution.PROFILES),
                    help="override the portfolio's persisted execution profile")
    ap.add_argument("--start", default=None,
                    help="explicit window start (proof runs; overrides --window)")
    ap.add_argument("--end", default=None, help="explicit window end")
    args = ap.parse_args()

    if args.config == "list":
        for c in CONFIGS:
            mark = f"  EXCLUDED: {EXCLUDED[c['id']]}" if c["id"] in EXCLUDED else ""
            log.info(f"{c['id']:<28} {c['strategy']:<24} {c['cadence']:<8}{mark}")
        return 0

    live = db.connect(args.db, read_only=True)
    try:
        run_replay(live, args.config, args.window,
                   scratch_root=Path(args.scratch_root),
                   screen_source=args.screen_source,
                   keep_scratch=args.keep_scratch,
                   write_result=not args.no_result, threads=args.threads,
                   initial_cash=args.initial_cash,
                   execution_profile=args.execution_profile,
                   override=((date.fromisoformat(args.start),
                              date.fromisoformat(args.end))
                             if args.start and args.end else None))
    finally:
        live.close()
    if not args.no_result:
        # Same as the queue path: a completed replay always leaves the reports
        # consistent with data/reports/backtests/results/.
        from farm.backtest import report
        for f in report.write_reports():
            log.info(f"[replay] report → {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
