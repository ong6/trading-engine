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
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from farm.walkforward import protocol, runner  # noqa: E402

SWEEPS_DIR = REPO_ROOT / "data" / "reports" / "sweeps"
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
            print(f"[sweep] {name}: skipping infeasible cell {slug} "
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
              scratch_root: Path = SCRATCH_ROOT, threads: int | None = 8,
              limit: int | None = None) -> dict:
    cands = expand(name)
    if limit:
        cands = cands[:limit]
    out_dir = Path(out_root) / name
    (out_dir / "results").mkdir(parents=True, exist_ok=True)

    todo = [_bench_book(live_con)] + cands
    print(f"[sweep] {name}: {len(cands)} candidate(s) + benchmark, {n_folds} folds each")

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
        })
    rows.sort(key=lambda r: -r["median_excess"])
    n_trials = n_trials if n_trials is not None else len(rows)

    bench_dd = min(v["validate"]["max_dd"] for v in bench.values())
    bench_med = statistics.median([v["validate"]["total_return"] for v in bench.values()])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    md = [
        f"# Sweep — `{name}`",
        "",
        f"_{len(rows)} candidate(s) · **{n_trials} trials** · {protocol.N_FOLDS}-fold "
        f"protocol · generated {stamp}._",
        "",
        "## Read this before the table",
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
        "| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        tag = " — _identical to the benchmark; not a result_" if r.get(
            "identical_to_benchmark") else ""
        md.append(f"| `{r['id'].replace(f'sweep__{name}__', '')}`{tag} | {r['n_folds']} | "
                  f"**{r['median_excess'] * 100:+.2f}%** | {r['mean_excess'] * 100:+.2f}% | "
                  f"{r['beat_bench'] * 100:.0f}% | {r['worst_dd'] * 100:.2f}% |")
    if not rows:
        md.append("| _no candidate produced a comparable fold_ | | | | | |")
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
           "drawdown no worse than the benchmark's. A row that is positive on median "
           "excess but beats EW in under half its folds is a skew bet, not an edge, and "
           "the distinction matters more than the headline number.",
           ""]
    (out_dir / "README.md").write_text("\n".join(md) + "\n")
    payload = {"sweep": name, "n_trials": n_trials, "generated": stamp,
               "rows": rows, "excluded": excluded}
    (out_dir / "ranking.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"[sweep] wrote {out_dir / 'README.md'}")
    return payload


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
    import duckdb
    from lib import db as _db

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

    live = duckdb.connect(args.db, read_only=True)
    try:
        run_sweep(live, args.grid, n_folds=args.folds, limit=args.limit,
                  anchor=date.fromisoformat(args.anchor) if args.anchor else None)
    finally:
        live.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
