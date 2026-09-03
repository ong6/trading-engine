#!/usr/bin/env python
"""Parameter sweeps over the EXISTING league strategy classes.

WHY THIS EXISTS. The 2026-08-17 walk-forward said the screen is the edge and
almost every rule layered on it subtracts value -- but it said that about the
*one* parameter set each book happens to be registered with. Whether
`template_top10_banded` is bad or merely badly parameterised is a question no
amount of live trading can answer in useful time (22 sessions, every |t| < 2),
and it is a question pure compute CAN answer: the strategy classes are already
parameterised, the box has ~31 idle cores, and the walk-forward now runs in
parallel. **This is search that costs CPU and zero tokens.**

WHAT IT IS NOT. A sweep does not create, promote or modify a league book. It
writes candidates to `data/reports/sweeps/<sweep_id>/` and nothing else. A
candidate becomes a book only when a human pre-registers it in
`sim/strategies/configs.py` with an expectation and a kill criterion, exactly
like every other book. The sweep narrows what is worth pre-registering; it never
does the pre-registering.

THE OVERFITTING PROBLEM, AND THE ONE THING THAT MAKES THIS SAFE. Testing 60
parameter sets and keeping the best does not find a good rule -- it finds the
luckiest of 60 draws. The best of N zero-skill trials looks better the larger N
gets, which is precisely why a sweep is dangerous if its trial count is hidden.
So every candidate this module runs is COUNTED, the count is written into the
report, and the ranking is by MEDIAN excess (robust to the single-fold outlier
that flipped every momentum verdict at 6 folds) rather than mean. The count is
the input `farm/stats.py:deflated_sharpe` needs to haircut a Sharpe honestly;
a sweep result quoted without its `n_trials` is not a result.

RANKING. Candidates are ranked by median excess return vs `ew_benchmark` over
the folds they share with it, because:
  * excess vs EW on the same universe cancels most of the survivorship bias
    that inflates every absolute number in this store (~+7pp/yr, disclosed);
  * the median, not the mean, because at 6 folds the mean was carried entirely
    by 2018-2021 for the whole momentum family.
`ew_benchmark` is always injected into a sweep so the comparison is computed on
identical folds rather than against a stored run from a different protocol.
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from engine.lib import db as _db
from engine.lib.settings import DATA_DIR, REPO_ROOT
from farm import stats as fstats
from farm.walkforward import protocol, runner
from engine.lib.log import get_logger

log = get_logger("sweep")

SWEEPS_DIR = DATA_DIR / "reports" / "sweeps"
SCRATCH_ROOT = REPO_ROOT / "scratch"
BENCH = "ew_benchmark"

# --------------------------------------------------------------------------- #
# the grids
# --------------------------------------------------------------------------- #
# Each grid sweeps ONE existing strategy class over parameters that class already
# reads. No new strategy code is involved, which is what makes a sweep cheap and
# safe to run unattended. Grids are deliberately COARSE: a fine grid buys
# resolution nobody can act on and inflates the trial count that every result
# then has to be deflated against.
GRIDS: dict[str, dict] = {
    # The concentration frontier. The 6-fold grid had only three points on it
    # (5 names / 10 names / 50 names) and they implied the whole return-vs-
    # drawdown trade; this fills it in properly.
    "concentration": {
        "strategy": "ew_benchmark",
        "base": {"cap": 50},
        "grid": {"cap": [10, 20, 30, 50, 75, 100]},
    },
    # Does inverse-vol weighting survive a change of lookback, and does the
    # single-name cap matter more than the weighting itself?
    "voltarget": {
        "strategy": "ew_voltarget",
        "base": {"cap": 50, "vol_lookback": 60, "min_obs": 40, "max_weight_mult": 3.0},
        "grid": {"vol_lookback": [20, 60, 120], "max_weight_mult": [1.5, 3.0, 5.0]},
        # vol_lookback=20 supplies 21 closes, below the base min_obs of 40, so
        # those three cells can never weight a name. They are dropped at expand()
        # time and named in the log — an impossible cell must not inflate the
        # trial count, and it must not be run and then reported as a 0% return.
        "feasible": lambda p: p["min_obs"] <= p["vol_lookback"] + 1,
    },
    # momo_stopped's whole thesis is the daily stop. Is 15% the right number, and
    # does the edge depend on holding 10 names rather than 5 or 20?
    "momo_stop": {
        "strategy": "momo_stopped",
        "base": {"n": 10, "band_rank": 20, "stop_frac": 0.85},
        "grid": {"n": [5, 10, 20], "stop_frac": [0.80, 0.85, 0.90]},
    },
    # Banding is a turnover control. Wider bands mean fewer trades; the question
    # is whether the drawdown follows the turnover down.
    # The CONTROL for `gross_voltarget`. ew_gross_voltarget ran at 47% / 31% of
    # the benchmark's vol over its first two folds, so comparing it to
    # ew_benchmark measures de-risking PLUS timing and credits all of it to the
    # timing. This grid supplies the de-risking-only leg; the difference between
    # the two grids is what varying exposure over time is actually worth.
    "static_exposure": {
        "strategy": "ew_static_exposure",
        "base": {"cap": 50, "exposure": 0.5, "cash_proxy": "BIL"},
        "grid": {"exposure": [0.3, 0.4, 0.5, 0.6, 0.8]},
        "feasible": lambda p: 0 < p["exposure"] <= 1,
    },
    "banding": {
        "strategy": "template_top10_banded",
        "base": {"n": 10, "band_rank": 20},
        "grid": {"n": [5, 10, 20], "band_rank": [15, 20, 30]},
    },
    # mr_overlay is the worst performer vs EW (-25.1% mean excess). If that is
    # the rule and not the parameters, no cell of this grid will clear EW.
    "meanrev": {
        "strategy": "mr_overlay",
        "base": {"rsi_max": 10, "down_closes": 3, "weight": 0.1,
                 "max_concurrent": 5, "time_stop": 10},
        "grid": {"rsi_max": [5, 10, 15], "time_stop": [5, 10, 20]},
    },
    # ----------------------------------------------------------------- #
    # The 2026-08-20 drawdown family. Every grid above varies WHICH names are
    # held or HOW they are weighted relative to one another, always at 100%
    # gross; the first and third of these vary GROSS EXPOSURE, which nothing in
    # this repo had ever done, and the second varies sector spread, which the
    # `concentration` grid did not (it varied total name COUNT).
    # ----------------------------------------------------------------- #
    # How hard should the exposure react, and over what window? max_leverage is
    # NOT swept: it stays at 1.0 (de-risk only) because levering a
    # survivorship-biased history manufactures return from a known data defect.
    "gross_voltarget": {
        "strategy": "ew_gross_voltarget",
        "base": {"cap": 50, "vol_target": 0.15, "vol_lookback": 60,
                 "max_leverage": 1.0, "min_obs": 20, "min_name_frac": 0.8,
                 "cash_proxy": "BIL"},
        "grid": {"vol_target": [0.10, 0.15, 0.20],
                 "vol_lookback": [40, 60, 120]},
        # A vol_lookback shorter than min_obs can never yield an estimate. No
        # cell of THIS grid violates it (40/60/120 all exceed min_obs=20), but
        # the predicate is declared anyway so widening the grid later cannot
        # reintroduce the `voltarget` vol_lookback=20 defect by accident.
        "feasible": lambda p: p["min_obs"] <= p["vol_lookback"],
    },
    # The screen put 38 of its top 50 names in ONE sector on 2026-08-19. Does
    # forcing spread cost return, buy drawdown relief, or neither?
    # NOTE: sector data in this store is a 2026 snapshot with no history — see
    # the look-ahead disclosure in sim/strategies/ew_sector_capped.py. Every
    # number this grid produces carries it.
    "sector_cap": {
        "strategy": "ew_sector_capped",
        "base": {"cap": 50, "max_per_sector": 10},
        "grid": {"max_per_sector": [5, 8, 10, 15]},
    },
    # A portfolio-level stop, against a written-down NEGATIVE prior: path
    # dependent de-risking usually whipsaws and loses more to re-entry than it
    # saves. dd_restore is held fixed rather than swept — a third axis would
    # triple the trial count every result is deflated against.
    "dd_throttle": {
        "strategy": "ew_dd_throttle",
        "base": {"cap": 50, "dd_trigger": 0.15, "derisk_frac": 0.5,
                 "dd_restore": 0.05, "cash_proxy": "BIL"},
        "grid": {"dd_trigger": [0.10, 0.15, 0.20], "derisk_frac": [0.0, 0.5]},
        # Without a hysteresis band the throttle trips and restores on one
        # reading; the strategy raises on it, so the cell must never be run.
        "feasible": lambda p: p["dd_restore"] < p["dd_trigger"],
    },
    # The stop multiple is the parameter a trend book is most sensitive to.
    "turtle_stops": {
        "strategy": "turtle_breakout",
        "base": {"entry_lookback": 55, "atr_period": 20, "stop_mult": 2.5,
                 "trail_mult": 3.0, "risk_frac": 0.0075, "max_positions": 10,
                 "max_weight": 0.15},
        "grid": {"stop_mult": [2.0, 2.5, 3.0], "trail_mult": [2.5, 3.0, 4.0]},
    },
}


def _cadence(strategy: str) -> str:
    """The class's own cadence, so a candidate trades on the same schedule the
    live book does. Read from the registry rather than hardcoded per grid."""
    from sim.strategies import get_strategy
    return get_strategy(strategy).cadence


def expand(name: str) -> list[dict]:
    """Grid -> candidate book dicts, in the shape run_book(book=...) expects."""
    if name not in GRIDS:
        raise SystemExit(f"[sweep] unknown grid {name!r}; have: {', '.join(sorted(GRIDS))}")
    spec = GRIDS[name]
    keys = sorted(spec["grid"])
    out = []
    for combo in itertools.product(*(spec["grid"][k] for k in keys)):
        params = dict(spec["base"])
        params.update(dict(zip(keys, combo)))
        slug = "__".join(f"{k}-{params[k]}" for k in keys)
        cid = f"sweep__{name}__{slug}"
        label = f"{spec['strategy']} [{', '.join(f'{k}={params[k]}' for k in keys)}]"
        # `cadence` MUST come from the class, not be left null: the replay inserts
        # this config into a scratch `portfolios` row and sim/league.py reads the
        # cadence back out to decide which sessions the book trades on. A null
        # cadence silently produces a book that never fires.
        ok = spec.get("feasible")
        if ok is not None and not ok(params):
            log.warning(f"[sweep] {name}: skipping infeasible cell {slug} "
                  f"(params the strategy can never satisfy)")
            continue
        cfg = {"id": cid, "name": label, "strategy": spec["strategy"],
               "cadence": _cadence(spec["strategy"]), "params": params}
        out.append({
            "id": cid,
            "name": label,
            "strategy": spec["strategy"],
            "config": cfg,
            # Stored as TEXT in `portfolios.config` and json.loads()'d by
            # league.generate_all -- None here throws deep inside the replay.
            "config_json": json.dumps(cfg),
            "excluded": None,
        })
    return out


def _bench_book(live_con) -> dict:
    """The live ew_benchmark row, injected so folds match exactly."""
    return runner.book_by_id(live_con, BENCH)


# --------------------------------------------------------------------------- #
def run_sweep(live_con, name: str, *, anchor: date | None = None,
              n_folds: int = protocol.N_FOLDS, out_root: Path = SWEEPS_DIR,
              # threads 8 -> 4 (2026-08-20): measured — at width 8, 4 DuckDB
              # threads per worker matched 2 (8 jobs in 55 s vs 57 s) and the
              # single-worker fold loop runs ~2.5 cores regardless; extra
              # threads only inflate load (a threads=8 sweep worker showed
              # 374% CPU / 101 OS threads for the same work).
              scratch_root: Path = SCRATCH_ROOT, threads: int | None = 4,
              limit: int | None = None) -> dict:
    cands = expand(name)
    if limit:
        cands = cands[:limit]
    out_dir = Path(out_root) / name
    (out_dir / "results").mkdir(parents=True, exist_ok=True)

    todo = [_bench_book(live_con)] + cands
    log.info(f"[sweep] {name}: {len(cands)} candidate(s) + benchmark, {n_folds} folds each")

    for b in todo:
        runner.run_book(live_con, b["id"], book=b, anchor=anchor, n_folds=n_folds,
                        scratch_root=Path(scratch_root),
                        results_dir=out_dir / "results",
                        write_result=True, verbose=True, threads=threads)
    return rank(name, out_root=out_root, n_trials=len(cands))


def _folds(path: Path) -> dict:
    d = json.loads(path.read_text())
    return {(f["first_session"], f["last_session"]): f
            for f in d.get("folds", []) if f.get("status") == "ok"}


def _grid_trial_count(name: str) -> int | None:
    """How many cells this grid ACTUALLY tries, read from the grid definition.

    `n_trials` is not decoration: it is the N that `farm/stats.py:deflated_sharpe`
    haircuts against, and a sweep result quoted without it is not a result. It
    used to default to `len(rows)` on a re-rank, which silently SHRINKS the trial
    count whenever a candidate was excluded (inert, or no shared fold) — i.e. the
    exact case where the grid tried more than it could rank, and the haircut
    should have got bigger rather than smaller. Read it from `expand()` instead,
    which already drops infeasible cells so an impossible parameter combination
    cannot inflate it either.
    """
    try:
        return len(expand(name))
    except SystemExit:
        return None          # ad-hoc grid name (a shakedown dir) — caller falls back


def _excess_sharpe(ex: list[float]) -> float | None:
    """Per-FOLD Sharpe of a candidate's excess-vs-EW series.

    The validate window is 12 months (D-WF1) and the windows are disjoint, so one
    fold excess is one annual excess return and this ratio is already at annual
    frequency — no sqrt(periods) rescaling, which would be inventing frequency
    the sample does not have.
    """
    if len(ex) < 2:
        return None
    sd = float(np.std(np.asarray(ex, dtype=float), ddof=1))
    if sd <= 0:
        return None
    return float(np.mean(ex)) / sd


def rank(name: str, *, out_root: Path = SWEEPS_DIR, n_trials: int | None = None) -> dict:
    out_dir = Path(out_root) / name
    res_dir = out_dir / "results"
    bench_p = res_dir / f"{BENCH}.json"
    if not bench_p.exists():
        raise SystemExit(f"[sweep] no benchmark result at {bench_p}")
    bench = _folds(bench_p)

    rows = []
    excluded = []          # candidates with no rankable fold, and WHY
    for p in sorted(res_dir.glob("sweep__*.json")):
        raw = json.loads(p.read_text())
        f = _folds(p)
        common = [k for k in f if k in bench]
        if not common:
            # NEVER a silent `continue`: a candidate that produced nothing
            # comparable is a finding about the candidate (usually an infeasible
            # parameter combination), and dropping it off the table makes the
            # sweep look like it tested more than it did.
            n_inert = sum(1 for fo in raw.get("folds", [])
                          if fo.get("status") == "inert")
            n_folds = len(raw.get("folds", []))
            why = (f"INERT — 0 fills in {n_inert}/{n_folds} fold(s); the book "
                   f"never traded, so it has no return to rank"
                   if n_inert else
                   "no fold shares a window with the benchmark")
            excluded.append({"id": raw["config_id"], "reason": why})
            continue
        ex = [f[k]["validate"]["total_return"] - bench[k]["validate"]["total_return"]
              for k in common]
        dds = [f[k]["validate"]["max_dd"] for k in common]
        # `_folds()` already keeps only status == "ok" folds, so an inert fold
        # never reaches `ex` and is never resampled. That matters: the bootstrap
        # below would happily treat a flat "book placed 0 fills" curve as an
        # observation, which is precisely the 2026-08-20 defect one layer up.
        ci = fstats.bootstrap_ci(ex, stat="median")
        # A cell whose base params ARE the benchmark's re-runs the benchmark and
        # scores an exact 0.00% excess in every fold — which sorts it to the top
        # of a table ranked by median excess. That is a self-comparison, not a
        # winner, and it gets said so rather than quietly leading the ranking
        # (2026-08-20: `concentration/cap-50` did exactly this).
        identical = all(e == 0.0 for e in ex)
        rows.append({
            "identical_to_benchmark": identical,
            "id": raw["config_id"],
            "n_folds": len(common),
            "median_excess": statistics.median(ex),
            "mean_excess": statistics.mean(ex),
            "beat_bench": sum(e > 0 for e in ex) / len(ex),
            "worst_dd": min(dds),
            "median_validate": statistics.median(
                [f[k]["validate"]["total_return"] for k in common]),
            # The error bar, and the pre-registered verdict read straight off it.
            "median_excess_ci": ci,
            "distinguishable": fstats.ci_verdict(ci),
            "excess_sharpe_per_fold": _excess_sharpe(ex),
            # The raw sample, so any interval in this file can be recomputed by
            # hand from the numbers stored beside it.
            "fold_excess": ex,
        })
    rows.sort(key=lambda r: -r["median_excess"])
    # Ranking order is UNCHANGED — still median excess, still descending. The CI
    # column is new information about each row, not a re-sort of the table.
    if n_trials is None:
        n_trials = _grid_trial_count(name)
    if n_trials is None:
        n_trials = len(rows) + len(excluded)

    bench_dd = min(v["validate"]["max_dd"] for v in bench.values())
    bench_med = statistics.median([v["validate"]["total_return"] for v in bench.values()])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    n_indistinct = sum(1 for r in rows if r["distinguishable"] == "INDISTINGUISHABLE")
    dsr = _deflate_top(rows, n_trials)

    md = [
        f"# Sweep — `{name}`",
        "",
        f"_{len(rows)} candidate(s) · **{n_trials} trials** · {protocol.N_FOLDS}-fold "
        f"protocol · bootstrap seed {fstats.BOOTSTRAP_SEED} · generated {stamp}._",
        "",
        "## Read this before the table",
        "",
        f"**{n_indistinct} of {len(rows)} ranked candidate(s) are "
        f"`INDISTINGUISHABLE` from `ew_benchmark`** — their 90% confidence "
        "interval on median excess contains 0, so this evidence does not "
        "establish even the SIGN of their edge, let alone its size. That is the "
        "headline of this table; the ordering below it is a tie-break among rows "
        "most of which are not separated from the benchmark at all.",
        "",
        f"**Every row here is one of {n_trials} parameter sets tried on the same data.** "
        "The best of N trials looks good at N=1 and looks good at N=60 for entirely "
        "different reasons, so the top row is NOT a finding — it is the starting point "
        "for one, and it has to survive a pre-registered forward test like anything "
        "else. Quote this table only with its trial count attached.",
        "",
        "Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at "
        "6 folds the mean excess of every momentum book was carried entirely by the "
        "2018-2021 window. Excess vs EW (same universe, same screen) is used rather "
        "than absolute return because it cancels most of the ~+7pp/yr survivorship "
        "inflation in this store.",
        "",
        f"Benchmark on these folds: median validate **{bench_med * 100:+.2f}%**, "
        f"worst-fold drawdown **{bench_dd * 100:.2f}%**.",
        "",
        "| Candidate | Distinguishable from EW? | Folds | Median excess | "
        "90% CI on median excess | Mean excess | Beats EW | Worst DD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        tag = " — _identical to the benchmark; not a result_" if r.get(
            "identical_to_benchmark") else ""
        md.append(f"| `{r['id'].replace(f'sweep__{name}__', '')}`{tag} "
                  f"| {_verdict_cell(r['distinguishable'])} | {r['n_folds']} | "
                  f"{r['median_excess'] * 100:+.2f}% | {_ci_cell(r['median_excess_ci'])} "
                  f"| {r['mean_excess'] * 100:+.2f}% | "
                  f"{r['beat_bench'] * 100:.0f}% | {r['worst_dd'] * 100:.2f}% |")
    if not rows:
        md.append("| _no candidate produced a comparable fold_ | | | | | | | |")

    md += _ci_method_block(rows)
    md += _dsr_block(dsr, n_trials)

    if excluded:
        md += ["",
               f"## Excluded — {len(excluded)} of {n_trials} candidate(s) produced no result",
               "",
               "These ran and are counted in the trial total; they are not ranked "
               "because they have nothing to rank. An inert candidate is a config "
               "defect, not a flat return.",
               "",
               "| Candidate | Why |", "|---|---|"]
        for e in excluded:
            md.append(f"| `{e['id'].replace(f'sweep__{name}__', '')}` | {e['reason']} |")
    md += ["",
           "## What a good row would look like",
           "",
           "Positive median excess AND beats-EW comfortably above 50% AND a worst-fold "
           "drawdown no worse than the benchmark's — **and a 90% CI on median excess "
           "that stays above 0**. Before 2026-08-20 only the first three were checked, "
           "which is how a -3.05% row came to sit at the top of a table as though the "
           "position meant something. A row that is positive on median "
           "excess but beats EW in under half its folds is a skew bet, not an edge, and "
           "the distinction matters more than the headline number.",
           ""]
    (out_dir / "README.md").write_text("\n".join(md) + "\n")
    payload = {"sweep": name, "n_trials": n_trials, "generated": stamp,
               "bootstrap": {"seed": fstats.BOOTSTRAP_SEED,
                             "draws": fstats.BOOTSTRAP_DRAWS,
                             "conf": fstats.BOOTSTRAP_CONF,
                             "statistic": "median",
                             "unit": "fold",
                             "n_indistinguishable": n_indistinct},
               "deflated_sharpe": dsr,
               "rows": rows, "excluded": excluded}
    (out_dir / "ranking.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    log.info(f"[sweep] wrote {out_dir / 'README.md'} "
          f"({n_indistinct}/{len(rows)} INDISTINGUISHABLE)")
    return payload


# --------------------------------------------------------------------------- #
# report fragments
# --------------------------------------------------------------------------- #
def _verdict_cell(v: str) -> str:
    """The verdict is the honest headline for nearly every row, so it is bold and
    shouty in the table rather than a footnote somebody has to go looking for."""
    if v == "INDISTINGUISHABLE":
        return "**INDISTINGUISHABLE**"
    if v == "NO-CI":
        return "_no interval — too few folds_"
    return f"**{v}**"


def _ci_cell(ci: dict | None) -> str:
    if ci is None:
        # Never a zero-filled interval. Fewer than three comparable folds means
        # there is nothing to resample and the cell says so.
        return "·"
    return f"[{ci['lo'] * 100:+.2f}%, {ci['hi'] * 100:+.2f}%]"


def _ci_method_block(rows: list[dict]) -> list[str]:
    ns = sorted({r["n_folds"] for r in rows})
    n_txt = str(ns[0]) if len(ns) == 1 else f"{min(ns)}–{max(ns)}"
    return [
        "",
        "## The interval, and what it is not",
        "",
        f"**Method.** Percentile bootstrap on the fold excesses, "
        f"{fstats.BOOTSTRAP_DRAWS:,} resamples, seed `{fstats.BOOTSTRAP_SEED}` "
        f"(fixed, so this table re-renders identically from unchanged inputs). "
        f"The resampling unit is the **fold** — n={n_txt} here — because a fold "
        "is one independent replay from the reference notional (D-WF2) over a "
        "validate window no other fold's validate window touches (D-WF1). Folds "
        "with status other than `ok` — including the `inert` status for a book "
        "that placed zero fills — are excluded before resampling; an inert fold "
        "is not evidence.",
        "",
        "**Verdict rule (pre-registered, mechanical).** If the 90% CI on median "
        "excess contains 0, the candidate is `INDISTINGUISHABLE` from "
        "`ew_benchmark` — **regardless of where it sits in the ranking**. No "
        "discretion, no exceptions for a good-looking point estimate.",
        "",
        "**Caveat, stated because it cuts against us.** Adjacent folds share "
        "twelve months of TRAIN window (train 24mo, step 12mo), and all folds "
        "come from one market history rather than ten independent ones. An "
        "i.i.d. bootstrap over overlapping folds therefore UNDERSTATES the true "
        "uncertainty: these intervals are a floor on the error bar. That makes "
        "an `INDISTINGUISHABLE` verdict stronger than it looks and any "
        "distinguishable verdict weaker.",
        "",
        "**At n=10 folds this is a crude instrument, and it is the right one.** "
        "A percentile bootstrap of a median at n=10 resolves roughly to the "
        "gaps between order statistics — it will not separate +0.5% from 0. "
        "Methods that would (block bootstrap over fold blocks, a stationary "
        "bootstrap, White's Reality Check across the grid) need a fold count in "
        "the high tens to mean anything, so they are named here and NOT used. "
        "The honest summary of a 10-fold sweep is that it can reject a large "
        "effect and cannot confirm a small one.",
    ]


def _deflate_top(rows: list[dict], n_trials: int) -> dict | None:
    """Multiple-testing haircut on the TOP genuine candidate's excess Sharpe.

    `farm/stats.py:deflated_sharpe` has existed since the historical-backtest
    farm was built and — until now — nothing in the sweep path called it, even
    though the sweep is the only workload in this repo that KNOWS its own trial
    count. That was the gap: the module docstring in this file has always said
    "the count is the input `farm/stats.py:deflated_sharpe` needs", and the
    count was being printed and then dropped on the floor.

    Two deliberate choices:

    * The series deflated is the candidate's **excess vs EW**, not its absolute
      return. The haircut has to apply to the statistic the selection was made
      on, and this table selects on excess. Deflating the absolute Sharpe would
      also be deflating ~+7pp/yr of survivorship inflation, which is not a skill
      claim anybody made.
    * V (the variance of trial Sharpes in the SR0 formula) is the OBSERVED
      cross-trial variance of this grid's excess Sharpes, not the estimator
      fallback in `stats.py`'s docstring. The fallback exists for callers that
      cannot see the other trials; a sweep can, so it uses the real thing and
      says so.
    """
    live = [r for r in rows if not r.get("identical_to_benchmark")]
    if not live:
        return None
    top = live[0]
    ex = top.get("fold_excess") or []
    if len(ex) < 3:
        # PSR/DSR needs a third and fourth moment. Two folds do not have one,
        # and a number would be invented rather than measured.
        return {"id": top["id"], "unavailable":
                f"only {len(ex)} comparable fold(s); DSR needs at least 3"}

    srs = [r["excess_sharpe_per_fold"] for r in live
           if r.get("excess_sharpe_per_fold") is not None]
    var_sr = None
    var_source = "estimator fallback (fewer than 3 trial Sharpes available)"
    if len(srs) >= 3:
        var_sr = float(np.var(np.asarray(srs, dtype=float), ddof=1))
        var_source = (f"observed variance of the {len(srs)} trial excess Sharpes "
                      f"in this grid")
    dsr, sr, sr0 = fstats.deflated_sharpe(np.asarray(ex, dtype=float),
                                          n_trials, var_sr=var_sr)
    return {"id": top["id"], "n_obs": len(ex), "n_trials": n_trials,
            "sharpe_raw": sr, "sr0_benchmark": sr0, "deflated_sharpe": dsr,
            "var_sr": var_sr, "var_source": var_source}


def _dsr_block(d: dict | None, n_trials: int) -> list[str]:
    if d is None:
        return []
    head = ["", "## Deflated Sharpe — the multiple-testing haircut", ""]
    if d.get("unavailable"):
        return head + [f"Not computed for `{d['id']}`: {d['unavailable']}. "
                       "No substitute number is printed."]
    name_only = d["id"].split("__", 2)[-1]
    return head + [
        f"Top genuine candidate `{name_only}`, on its **excess-vs-EW** series "
        f"({d['n_obs']} folds; each fold is a 12-month validate window, so this "
        f"is already an annual-frequency Sharpe and is NOT rescaled).",
        "",
        "| | |",
        "|---|---|",
        f"| Raw Sharpe (excess vs EW, per fold) | **{d['sharpe_raw']:+.3f}** |",
        f"| Trials searched (N) | {d['n_trials']} |",
        f"| SR0 — Sharpe the luckiest of {d['n_trials']} zero-skill trials would "
        f"be expected to show | {d['sr0_benchmark']:+.3f} |",
        f"| **Deflated Sharpe (DSR) = P(true excess Sharpe > SR0)** | "
        f"**{d['deflated_sharpe']:.3f}** |",
        "",
        f"V in the SR0 formula is the {d['var_source']}.",
        "",
        "**How to read it.** DSR is a probability, not a Sharpe. Above ~0.95 the "
        "top cell's Sharpe is hard to explain as the best of N lucky draws; "
        "below that it is not distinguishable from the maximum a zero-skill "
        "search of this size produces by construction. Bailey & Lopez de Prado "
        "(2014).",
        "",
        f"**Small-sample warning.** The PSR machinery underneath DSR is a normal "
        f"approximation whose accuracy comes from the observation count, and "
        f"there are {d['n_obs']} observations here — not the hundreds the "
        f"formula was written for. Skew and kurtosis estimated from "
        f"{d['n_obs']} points are themselves very noisy. Treat this number as a "
        "direction-of-travel check on the haircut, not as a test.",
        "",
        f"**N counts this grid only.** {n_trials} cells were tried here; the "
        "store has run more parameter sets than that across all grids, and a "
        "reader picking the best cell across grids is searching a larger N than "
        "this row is deflated against. The haircut below is therefore a LOWER "
        "bound.",
    ]


# --------------------------------------------------------------------------- #
def run_job(params: dict, con, meta_path=None) -> None:
    """Queue dispatch (job kind 'sweep'), params {grid, n_folds?, limit?}."""
    name = params.get("grid")
    if not name:
        raise ValueError("sweep job needs params {'grid': ...}")
    anchor = params.get("anchor")
    run_sweep(con, name,
              anchor=date.fromisoformat(anchor) if anchor else None,
              n_folds=int(params.get("n_folds", protocol.N_FOLDS)),
              out_root=Path(params.get("out_root") or SWEEPS_DIR),
              scratch_root=Path(params.get("scratch_root") or SCRATCH_ROOT),
              limit=params.get("limit"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Parameter sweep over league strategy classes.")
    ap.add_argument("--grid", required=True, help=f"one of: {', '.join(sorted(GRIDS))}, or 'list'")
    ap.add_argument("--db", default=str(_db.DEFAULT_DB))
    ap.add_argument("--folds", type=int, default=protocol.N_FOLDS)
    ap.add_argument("--anchor", default=None)
    ap.add_argument("--limit", type=int, default=None, help="first N candidates (smoke test)")
    ap.add_argument("--rank-only", action="store_true", help="re-rank existing results")
    args = ap.parse_args()

    if args.grid == "list":
        for k, v in sorted(GRIDS.items()):
            print(f"{k:<16} {v['strategy']:<24} {len(expand(k)):>3} candidates")
        return 0
    if args.rank_only:
        rank(args.grid)
        return 0

    live = _db.connect(args.db, read_only=True)
    try:
        run_sweep(live, args.grid, n_folds=args.folds, limit=args.limit,
                  anchor=date.fromisoformat(args.anchor) if args.anchor else None)
    finally:
        live.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
