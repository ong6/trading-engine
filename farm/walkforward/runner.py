#!/usr/bin/env python
"""Walk-forward re-validate ONE active league book — the workload's unit of work.

Same honesty rule as the historical-backtest farm: **nothing about a strategy is
reimplemented here.** A fold is a real `sim/league.py.step()` loop over real
sessions — orders from the real strategy class, fills from the real
`sim/fills.py` (t+1 open, slippage tiers, liquidity guard, no same-bar fill,
never an invented bar), dividends from the real phase a0. This module only
decides WHICH sessions each fold covers and where the equity curve is cut.

Shape of one job (one book, all its folds):

    live store (READ ONLY)
      └─ scratch/wf__<book>__p<pid>/replay.duckdb  built ONCE for the whole span
           ├─ hist_screen over the span's sessions ONCE (books that read it)
           └─ per fold: wipe sim tables → insert the LIVE portfolios row →
              step every session train_start…validate_end → slice sim_equity at
              split_date → stats(train), stats(validate)

Building the scratch once per book instead of once per fold is the whole reason
this is a per-book job rather than a per-fold job: the fold windows overlap by
construction, so N folds share one price export and one screen pass.

Entry points:
    CLI:   farm/walkforward/runner.py --config template_top5
    Queue: run_job(params, con, meta_path=None) — job kind 'walkforward',
           params {"config_id": …, optional protocol overrides}
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import db  # noqa: E402
from sim import portfolio as _pf  # noqa: E402
from lib import leverage as lev  # noqa: E402

from sim import league  # noqa: E402
from sim.schema import INITIAL_CASH  # noqa: E402

if __package__:
    from . import protocol
else:  # pragma: no cover - script invocation
    from farm.walkforward import protocol

from farm.backtest import hist_screen, stats  # noqa: E402
from farm.backtest.replay import (  # noqa: E402
    DEFAULT_REQUIRED, NEEDS_SCREEN, REQUIRED, REQUIRED_LOOKBACK, build_scratch,
)

SCRATCH_ROOT = REPO_ROOT / "scratch"
WF_DIR = REPO_ROOT / "data" / "reports" / "walkforward"
RESULTS_DIR = WF_DIR / "results"

# Sim tables wiped between folds. `portfolios` is included on purpose: each fold
# re-creates the book from the LIVE config (D-WF4) with a fresh reference
# notional and a `created` stamp at the fold's own start (D-WF2).
SIM_TABLES = ("sim_dividends", "sim_fills", "sim_orders", "sim_positions",
              "sim_equity", "portfolios")


# --------------------------------------------------------------------------- #
# the live league's own books
# --------------------------------------------------------------------------- #
def active_books(live_con) -> list[dict]:
    """Every active row of the LIVE `portfolios` table — league.generate_all's
    exact source — with the excluded books removed and the reason kept."""
    rows = live_con.execute(
        "SELECT id, name, strategy, config FROM portfolios WHERE active "
        "ORDER BY id").fetchall()
    out = []
    for pid, name, strat, cfg_json in rows:
        try:
            cfg = json.loads(cfg_json) if cfg_json else {}
        except (TypeError, json.JSONDecodeError):
            cfg = {}
        out.append({"id": pid, "name": name, "strategy": strat, "config": cfg,
                    "config_json": cfg_json,
                    "excluded": protocol.excluded_reason(pid, strat)})
    return out


def book_by_id(live_con, config_id: str) -> dict:
    for b in active_books(live_con):
        if b["id"] == config_id:
            return b
    raise SystemExit(f"[wf] {config_id!r} is not an active row in `portfolios` "
                     f"(the live league's book list). Nothing to re-validate.")


def data_floor(live_con, strategy: str) -> date:
    """Earliest session at which this book's required tickers all have enough bars."""
    floors = []
    for tk in REQUIRED.get(strategy, DEFAULT_REQUIRED):
        row = live_con.execute(
            "SELECT date FROM prices WHERE ticker = ? ORDER BY date "
            "LIMIT 1 OFFSET ?", [tk, REQUIRED_LOOKBACK]).fetchone()
        if row is None:
            raise SystemExit(f"[wf] required ticker {tk} has fewer than "
                             f"{REQUIRED_LOOKBACK + 1} bars")
        floors.append(row[0])
    return max(floors)


# --------------------------------------------------------------------------- #
# per-fold replay
# --------------------------------------------------------------------------- #
def _reset_sim(con) -> None:
    for t in SIM_TABLES:
        con.execute(f"DELETE FROM {t}")


def _insert_book(con, book: dict, created: date) -> None:
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash)"
        " VALUES (?, ?, ?, ?, ?, TRUE, ?)",
        [book["id"], book["name"], book["strategy"], book["config_json"],
         created, INITIAL_CASH])


def _slice(eq: list[tuple], lo: date | None, hi: date | None) -> tuple[list, list]:
    rows = [r for r in eq
            if (lo is None or r[0] >= lo) and (hi is None or r[0] <= hi)]
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def run_fold(con, book: dict, fold: protocol.Fold, sessions: list[date],
             data_dir: Path, verbose: bool = True) -> dict:
    """Replay one fold in the scratch store and return its two stat packs."""
    if len(sessions) < 3:
        return {**fold.as_dict(), "status": "skipped",
                "reason": f"only {len(sessions)} session(s) in the fold window"}

    t0 = time.time()
    _reset_sim(con)
    _insert_book(con, book, sessions[0])
    for d in sessions:
        league.step(con, d, data_dir, rerun=False, verbose=False)

    eq = con.execute(
        "SELECT date, equity FROM sim_equity WHERE portfolio_id = ? ORDER BY date",
        [book["id"]]).fetchall()
    if len(eq) < 3:
        return {**fold.as_dict(), "status": "skipped",
                "reason": f"only {len(eq)} equity row(s) written"}

    split = max([r[0] for r in eq if r[0] <= fold.split_date],
                default=eq[0][0])
    tr_d, tr_e = _slice(eq, None, split)
    # The validate slice is BASED at the split row, so validate total return is
    # E_end / E_split − 1 and the two windows abut without double-counting a day.
    va_d, va_e = _slice(eq, split, None)

    bil = stats.bil_daily_returns(con, eq[0][0], eq[-1][0])
    n_fills = con.execute(
        "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ?",
        [book["id"]]).fetchone()[0]
    n_rej = con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ? AND "
        "status = 'rejected'", [book["id"]]).fetchone()[0]
    n_val_fills = con.execute(
        "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ? AND fill_date > ?",
        [book["id"], split]).fetchone()[0]
    n_div = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM sim_dividends "
        "WHERE portfolio_id = ?", [book["id"]]).fetchone()

    # A book that never bought anything did not "return 0.00%" — it did nothing.
    # Its equity curve is the initial cash, flat, and every stat derived from it
    # (return, drawdown, Sharpe) is an artefact of that, not a measurement. Three
    # separate defects in this codebase have surfaced as a plausible-looking 0%
    # row rather than an error (NEEDS_SCREEN allow-list, null cadence, and
    # ew_voltarget's min_obs > lookback), so the fold is labelled INERT and
    # excluded from every summary rather than ranked against real candidates.
    if n_fills == 0:
        return {**fold.as_dict(), "status": "inert",
                "sessions": len(sessions),
                "first_session": sessions[0].isoformat(),
                "last_session": sessions[-1].isoformat(),
                "runtime_s": round(time.time() - t0, 1),
                "reason": "0 fills over the whole fold — the book never traded, "
                          "so its flat equity is not a result"}

    out = {
        **fold.as_dict(),
        "status": "ok",
        "sessions": len(sessions),
        "first_session": sessions[0].isoformat(),
        "last_session": sessions[-1].isoformat(),
        "split_session": split.isoformat(),
        "n_fills": n_fills,
        "n_validate_fills": n_val_fills,
        "n_rejected": n_rej,
        "n_dividend_credits": n_div[0],
        "dividend_cash": float(n_div[1]),
        "runtime_s": round(time.time() - t0, 1),
        "train": stats.equity_stats(tr_d, tr_e, bil),
        "validate": stats.equity_stats(va_d, va_e, bil),
    }
    if verbose:
        v, t = out["validate"], out["train"]
        print(f"[wf]   fold {fold.index}: train {_pct(t.get('total_return'))} "
              f"({t.get('start_date')}→{t.get('end_date')}) | "
              f"validate {_pct(v.get('total_return'))} "
              f"({v.get('start_date')}→{v.get('end_date')}) "
              f"maxDD {_pct(v.get('max_dd'))} fills {n_val_fills} "
              f"[{out['runtime_s']}s]", flush=True)
    return out


# --------------------------------------------------------------------------- #
# the job
# --------------------------------------------------------------------------- #
def run_book(live_con, config_id: str, *,
             train_months: int = protocol.TRAIN_MONTHS,
             validate_months: int = protocol.VALIDATE_MONTHS,
             step_months: int = protocol.STEP_MONTHS,
             n_folds: int = protocol.N_FOLDS,
             anchor: date | None = None,
             scratch_root: Path = SCRATCH_ROOT,
             results_dir: Path = RESULTS_DIR,
             keep_scratch: bool = False, write_result: bool = True,
             verbose: bool = True, threads: int | None = 16,
             mem_mb: int | None = 8000, book: dict | None = None) -> dict:
    # `book` is the CANDIDATE seam (farm/sweep). Production passes nothing and
    # the config is read from the live `portfolios` row, which is the whole
    # point of the walk-forward: it re-validates the rule the league is actually
    # trading, not a re-typed copy of it. A caller that passes `book` is
    # explicitly testing something that is NOT in the league -- a parameter
    # variant or a proposed rule -- and such a run must write to its own
    # results_dir so a candidate can never be mistaken for a live book's record.
    book = book if book is not None else book_by_id(live_con, config_id)
    if book["excluded"]:
        raise SystemExit(f"[wf] {config_id} is excluded: {book['excluded']}")

    t0 = time.time()
    if anchor is None:
        anchor = live_con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    folds = protocol.make_folds(anchor, train_months=train_months,
                                validate_months=validate_months,
                                step_months=step_months, n_folds=n_folds)

    floor = data_floor(live_con, book["strategy"])
    kept: list[protocol.Fold] = []
    dropped: list[dict] = []
    clamped_ids: set[int] = set()
    for f in folds:
        # A fold whose VALIDATE window opens at or before the data floor has no
        # out-of-sample content for this book — dropped and said so, never
        # silently shortened into something that looks like a result.
        if f.split_date <= floor:
            dropped.append({**f.as_dict(), "status": "dropped",
                            "reason": f"validate window opens {f.split_date}, at "
                                      f"or before this book's data floor {floor}"})
            continue
        # A short TRAIN window is a weaker baseline, not a wrong one: clamp and label.
        if f.train_start < floor:
            f = protocol.Fold(index=f.index, train_start=floor,
                              split_date=f.split_date,
                              validate_end=f.validate_end)
            clamped_ids.add(f.index)
        kept.append(f)

    if not kept:
        raise SystemExit(f"[wf] {config_id}: no fold survives the data floor {floor}")

    span_start = min(f.train_start for f in kept)
    span_end = max(f.validate_end for f in kept)
    span_start = live_con.execute(
        "SELECT MIN(date) FROM prices WHERE date >= ?", [span_start]).fetchone()[0]
    span_end = live_con.execute(
        "SELECT MAX(date) FROM prices WHERE date <= ?", [span_end]).fetchone()[0]
    all_sessions = hist_screen.sessions_between(live_con, span_start, span_end)

    print(f"[wf] {config_id} ({book['strategy']}): {len(kept)} fold(s), "
          f"{len(all_sessions)} sessions {span_start} → {span_end} "
          f"(anchor {anchor}, floor {floor})", flush=True)
    print(protocol.describe(anchor, kept, train_months=train_months,
                            validate_months=validate_months,
                            step_months=step_months), flush=True)

    # The scratch dir is namespaced by PID, not by config_id alone. Every sweep
    # injects `ew_benchmark` as its benchmark book, so two sweeps running
    # concurrently as batch children both derived `scratch/wf__ew_benchmark/`
    # and destroyed each other — one died on the replay.duckdb.wal lock, the
    # other on a corporate_actions.parquet the first had just rmtree'd
    # (measured 2026-08-20, jobs 209/210). Folds of ONE book still share ONE
    # scratch store, which is the invariant that matters; processes never do.
    scratch_dir = Path(scratch_root) / f"wf__{config_id}__p{os.getpid()}"
    shutil.rmtree(scratch_dir, ignore_errors=True)
    result: dict = {}
    try:
        t_scratch = time.time()
        db_path = build_scratch(live_con, scratch_dir, span_start, span_end,
                                verbose=verbose)
        scratch_s = time.time() - t_scratch

        con = db.connect(db_path)
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        if mem_mb:
            con.execute(f"SET memory_limit = '{int(mem_mb)}MB'")
        con.execute(f"SET temp_directory = '{scratch_dir}'")

        t_screen = time.time()
        n_screen = 0
        # Resolved once per book and RECORDED in the result JSON below — see the
        # same note in farm/backtest/replay.py. Every fold of a book shares one
        # screen, so one policy per book is the right granularity.
        policy = lev.resolve_policy(None)
        if book["strategy"] in NEEDS_SCREEN:
            n_screen = hist_screen.screen_sessions(
                con, all_sessions, membership="prices", passing_only=True,
                universe_policy=policy, verbose=verbose)
        screen_s = time.time() - t_screen

        fold_results = []
        for f in kept:
            fs = [d for d in all_sessions
                  if f.train_start <= d <= f.validate_end]
            fr = run_fold(con, book, f, fs, scratch_dir, verbose=verbose)
            fr["train_start_clamped_to_data_floor"] = f.index in clamped_ids
            fold_results.append(fr)
        con.close()

        result = {
            "config_id": config_id,
            "name": book["name"],
            "strategy": book["strategy"],
            "cadence": book["config"].get("cadence"),
            "expectation": book["config"].get("expectation"),
            "kill_criterion": book["config"].get("kill_criterion"),
            "description": book["config"].get("description"),
            "initial_cash": INITIAL_CASH,
            # Stamped so results produced under different fill arithmetic can
            # never be silently compared. See sim/portfolio.FILL_MODEL_VERSION.
            "fill_model": _pf.FILL_MODEL_VERSION,
            "data_floor": floor.isoformat(),
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocol": protocol.protocol_dict(
                anchor, kept, train_months=train_months,
                validate_months=validate_months, step_months=step_months),
            "dropped_folds": [d for d in dropped if d],
            "screen_rows": n_screen,
            "universe_policy": policy,
            "screen_source": "hist" if book["strategy"] in NEEDS_SCREEN
                             else "not-used",
            "span_start": span_start.isoformat(),
            "span_end": span_end.isoformat(),
            "sessions": len(all_sessions),
            "scratch_s": round(scratch_s, 1),
            "screen_s": round(screen_s, 1),
            "runtime_s": round(time.time() - t0, 1),
            "folds": fold_results,
            "summary": summarize(fold_results),
        }
        if write_result:
            results_dir.mkdir(parents=True, exist_ok=True)
            out = results_dir / f"{config_id}.json"
            out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(f"[wf] wrote {out}", flush=True)
    finally:
        if not keep_scratch:
            shutil.rmtree(scratch_dir, ignore_errors=True)

    s = result.get("summary", {})
    wr = s.get("validate_win_rate")
    n_inert = s.get("n_folds_inert") or 0
    if n_inert:
        print(f"[wf] {config_id}: {n_inert} INERT fold(s) — the book placed 0 "
              f"fills there; excluded from the summary", flush=True)
    print(f"[wf] {config_id} done in {result.get('runtime_s')}s: "
          f"{s.get('n_folds_ok')} fold(s), validate win rate "
          f"{'·' if wr is None else f'{wr * 100:.0f}%'}, mean validate "
          f"{_pct(s.get('mean_validate_total'))}, mean decay "
          f"{_pct(s.get('mean_decay_cagr'))}", flush=True)
    return result


def summarize(folds: list[dict]) -> dict:
    ok = [f for f in folds if f.get("status") == "ok"]
    vt = [f["validate"].get("total_return") for f in ok
          if f["validate"].get("total_return") is not None]
    vc = [f["validate"].get("cagr") for f in ok
          if f["validate"].get("cagr") is not None]
    tc = [f["train"].get("cagr") for f in ok if f["train"].get("cagr") is not None]
    dd = [f["validate"].get("max_dd") for f in ok
          if f["validate"].get("max_dd") is not None]
    sh = [f["validate"].get("sharpe") for f in ok
          if f["validate"].get("sharpe") is not None
          and f["validate"]["sharpe"] == f["validate"]["sharpe"]]
    decay = [f["validate"]["cagr"] - f["train"]["cagr"] for f in ok
             if f["validate"].get("cagr") is not None
             and f["train"].get("cagr") is not None]
    inert = [f for f in folds if f.get("status") == "inert"]
    return {
        "n_folds_ok": len(ok),
        # Counted and carried, never dropped quietly: a candidate that is inert
        # in most of its folds is a broken config, and that has to be readable
        # off the summary without opening the fold list.
        "n_folds_inert": len(inert),
        "validate_win_rate": (sum(1 for v in vt if v > 0) / len(vt)) if vt else None,
        "mean_validate_total": (sum(vt) / len(vt)) if vt else None,
        "median_validate_total": _median(vt),
        "worst_validate_total": min(vt) if vt else None,
        "best_validate_total": max(vt) if vt else None,
        "mean_validate_cagr": (sum(vc) / len(vc)) if vc else None,
        "mean_train_cagr": (sum(tc) / len(tc)) if tc else None,
        "mean_decay_cagr": (sum(decay) / len(decay)) if decay else None,
        "mean_validate_sharpe": (sum(sh) / len(sh)) if sh else None,
        "worst_validate_max_dd": min(dd) if dd else None,
        "latest_validate_total": (ok[-1]["validate"].get("total_return")
                                  if ok else None),
        "total_validate_fills": sum(f.get("n_validate_fills", 0) for f in ok),
    }


def _median(xs: list[float]):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{v * 100:+.2f}%"


# --------------------------------------------------------------------------- #
# queue entry point
# --------------------------------------------------------------------------- #
def run_job(params: dict, con, meta_path=None) -> None:
    """Queue dispatch (job kind 'walkforward'), params {config_id, …overrides}.

    `con` is the runner's LIVE connection and is used READ-ONLY here (SELECTs
    plus `COPY … TO` parquet inside build_scratch); every write goes to the
    job's scratch store or to data/reports/walkforward/.
    """
    cfg_id = params.get("config_id")
    if not cfg_id:
        raise ValueError("walkforward job needs params {'config_id': …}")
    anchor = params.get("anchor")
    # `results_dir` / `scratch_root` exist so a shakedown on a COPY of the store
    # can be driven through the real queue path without writing proof numbers
    # into the committed data/reports/walkforward/. Production jobs omit both.
    results_dir = Path(params.get("results_dir") or RESULTS_DIR)
    scratch_root = Path(params.get("scratch_root") or SCRATCH_ROOT)
    run_book(
        con, cfg_id,
        train_months=int(params.get("train_months", protocol.TRAIN_MONTHS)),
        validate_months=int(params.get("validate_months",
                                       protocol.VALIDATE_MONTHS)),
        step_months=int(params.get("step_months", protocol.STEP_MONTHS)),
        n_folds=int(params.get("n_folds", protocol.N_FOLDS)),
        anchor=date.fromisoformat(anchor) if anchor else None,
        results_dir=results_dir, scratch_root=scratch_root,
        mem_mb=params.get("mem_mb", 8000),
    )
    if __package__:
        from . import report
    else:  # pragma: no cover
        from farm.walkforward import report
    report.write_reports(results_dir=results_dir, out_dir=results_dir.parent)


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Walk-forward re-validate one active league book.")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="LIVE store (read-only)")
    ap.add_argument("--config", required=True, help="book id, or 'list'")
    ap.add_argument("--train-months", type=int, default=protocol.TRAIN_MONTHS)
    ap.add_argument("--validate-months", type=int, default=protocol.VALIDATE_MONTHS)
    ap.add_argument("--step-months", type=int, default=protocol.STEP_MONTHS)
    ap.add_argument("--folds", type=int, default=protocol.N_FOLDS)
    ap.add_argument("--anchor", default=None, help="window anchor (default: last session)")
    ap.add_argument("--scratch-root", default=str(SCRATCH_ROOT))
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--keep-scratch", action="store_true")
    ap.add_argument("--no-result", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--threads", type=int, default=16)
    args = ap.parse_args()

    import duckdb
    live = duckdb.connect(args.db, read_only=True)
    try:
        if args.config == "list":
            for b in active_books(live):
                mark = f"  EXCLUDED: {b['excluded']}" if b["excluded"] else ""
                print(f"{b['id']:<28} {b['strategy']:<24} "
                      f"{str(b['config'].get('cadence')):<8}{mark}")
            return 0
        run_book(live, args.config,
                 train_months=args.train_months,
                 validate_months=args.validate_months,
                 step_months=args.step_months, n_folds=args.folds,
                 anchor=date.fromisoformat(args.anchor) if args.anchor else None,
                 scratch_root=Path(args.scratch_root),
                 results_dir=Path(args.results_dir),
                 keep_scratch=args.keep_scratch,
                 write_result=not args.no_result, threads=args.threads)
    finally:
        live.close()
    if not args.no_result and not args.no_report:
        from farm.walkforward import report
        for f in report.write_reports(results_dir=Path(args.results_dir)):
            print(f"[wf] report → {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
