"""Monthly-granularity re-report of the walk-forward (docs/evaluation-2026-09-02.md §2).

Why this exists. The fold-level report (`report.py`) bootstraps n=10 fold returns
per book, so "50% power at +7pp/yr" is a property of the chosen unit, not of the
data: the same non-overlapping validate windows contain ~120 paired monthly
returns (book − control). This module re-reports every walk-forwarded book on
that finer unit, using the SAME replays, with dependence handled explicitly
(stationary block bootstrap, Newey-West).

Inputs (all on disk, nothing replayed):

  * `data/reports/walkforward/results/<book>.json` — one fold per validate
    window. Since 2026-09-02 `runner.run_fold` also writes
    `validate_monthly_equity` = [[YYYY-MM, month-end equity], ...] per fold
    (base row = the split session). Fold files written before that carry only
    summary stats, so their monthly series does not exist and the walk-forward
    table below is empty until the next weekly run.
  * `data/reports/backtests/results/<book>__15y.json` — the continuous 15-year
    replay's `monthly_equity`. Used ONLY as a labelled PROXY (`--source proxy`):
    one continuous path rather than ten independent fold replays, and fill model
    v1 rather than v2. Months are assigned to folds by the frozen protocol dates
    and only validate months are kept, so the control pairing and fold-10
    exclusion are identical to the walk-forward version.

Verdict rule (pre-registered here, mechanical — see the report header):

  BEATS            90% stationary-block-bootstrap CI on the MEDIAN monthly excess
                   lies entirely above 0 AND Newey-West t on the MEAN ≥ +1.645.
  TRAILS           the mirror image (CI entirely below 0 AND NW t ≤ −1.645).
  INDISTINGUISHABLE  everything else with ≥ MIN_MONTHS paired months.
  NO-DATA          fewer than MIN_MONTHS paired months.

The median carries the verdict because the fold-level PASS keyed on a mean that
one 2018-21 fold could hijack; the NW t on the mean is a required corroboration
so a median win with a strongly negative mean (or the reverse) cannot pass. The
deflated Sharpe on the pooled months is context (bar 0.95, as in farm/stats.py),
not part of the rule.

Controls: single-name books vs `ew_benchmark` (same screen, same universe);
asset-allocation books (ETF / sleeve books, `SPY_BOOKS`) vs `spy_benchmark`.

In-sample fold: fold 10 (validate 2025-08-28→2026-08-28) is the data the July
2026 registrations were written against; it is dropped for every book whose
`portfolios.created` is before `INSAMPLE_CUTOFF` (2026-08-01). Registration
dates come from the result JSON (`registered`, persisted by the runner since
2026-09-02) with a static fallback snapshot of the live table taken 2026-09-02.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from engine.lib.settings import DATA_DIR
from engine.lib.settings import REPO_ROOT as ROOT  # noqa: F401
from farm import stats as fstats

WF_DIR = DATA_DIR / "reports" / "walkforward"
RESULTS_DIR = WF_DIR / "results"
BACKTEST_RESULTS_DIR = DATA_DIR / "reports" / "backtests" / "results"

EW = "ew_benchmark"
SPY = "spy_benchmark"
CONTROLS = (EW, SPY)
# Asset-allocation books: hold ETFs / sleeves, never the screen's single names.
SPY_BOOKS = frozenset({"dual_momentum", "dual_momentum_gated", "sector_momentum",
                       "agentic_alloc", "agentic_alloc_frozen", "macro_composite"})

INSAMPLE_CUTOFF = "2026-08-01"       # registered before this ⇒ fold 10 is in-sample
INSAMPLE_FOLD_INDEX = 10
# Snapshot of `SELECT id, created FROM portfolios` on the live store, 2026-09-02.
# Only consulted when a result JSON predates the runner writing `registered`.
REGISTERED_FALLBACK = {
    "adaptive_mr": "2026-08-03", "adaptive_mr_frozen": "2026-08-03",
    "agentic_alloc": "2026-08-03", "agentic_alloc_frozen": "2026-08-03",
    "dual_momentum": "2026-07-17", "dual_momentum_gated": "2026-07-17",
    "earnings_context_pead": "2026-08-03", "ew_benchmark": "2026-07-17",
    "ew_trend_gated": "2026-08-18", "ew_voltarget": "2026-08-18",
    "high_52wk": "2026-07-28", "low_vol": "2026-07-28", "macro_composite": "2026-08-03",
    "momo_stopped": "2026-07-28", "mr_overlay": "2026-07-17",
    "mr_overlay_gated": "2026-07-17", "news_gated_momo": "2026-08-03",
    "pead_ear": "2026-07-28", "sector_momentum": "2026-07-28",
    "spy_benchmark": "2026-07-17", "stop_tuner_turtle": "2026-08-03",
    "template_top10_banded": "2026-07-17", "template_top10_banded_gated": "2026-07-17",
    "template_top5": "2026-07-17", "template_top5_gated": "2026-07-17",
    "turtle_breakout": "2026-07-28",
}

MEAN_BLOCK_MONTHS = 4          # stationary bootstrap: geometric block, mean 4 months
NW_LAG = 3                     # Bartlett kernel, 3 monthly lags
MIN_MONTHS = 24
CONF = fstats.BOOTSTRAP_CONF
N_BOOT = fstats.BOOTSTRAP_DRAWS
SEED = fstats.BOOTSTRAP_SEED
T_CRIT = 1.645                 # one-sided 5% on the required side
DSR_BAR = 0.95


# --------------------------------------------------------------------------- #
# monthly series
# --------------------------------------------------------------------------- #
def month_end_points(dates, equity) -> list[list]:
    """[[YYYY-MM, last equity in that month], ...] in date order.

    Accepts `date` objects or ISO strings. Used by the runner to persist the
    validate slice, so the first point is the split session's month.
    """
    out: dict[str, float] = {}
    for d, e in zip(dates, equity):
        m = d if isinstance(d, str) else d.isoformat()
        out[m[:7]] = float(e)
    return [[m, out[m]] for m in sorted(out)]


def monthly_returns(points) -> list[tuple[str, float]]:
    """Consecutive month-end ratios; each return is labelled by the LATER month."""
    pts = [(str(m), float(e)) for m, e in points]
    return [(pts[i][0], pts[i][1] / pts[i - 1][1] - 1.0)
            for i in range(1, len(pts)) if pts[i - 1][1] > 0]


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def stationary_bootstrap_indices(n: int, n_boot: int, mean_block: float, rng) -> np.ndarray:
    """Politis & Romano (1994) stationary bootstrap index matrix (n_boot, n).

    Block lengths are geometric with mean `mean_block`; blocks wrap circularly.
    `rng` needs `.integers(lo, hi, size=)` and `.random(size)` — a numpy
    Generator, or a scripted stand-in in tests. mean_block ≤ 1 ⇒ iid resample.
    """
    p = 1.0 if mean_block <= 1 else 1.0 / float(mean_block)
    starts = rng.integers(0, n, size=(n_boot, n))
    cont = rng.random((n_boot, n)) >= p          # True ⇒ continue the running block
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for j in range(1, n):
        idx[:, j] = np.where(cont[:, j], (idx[:, j - 1] + 1) % n, starts[:, j])
    return idx


def block_bootstrap_ci(sample, *, stat: str = "median", conf: float = CONF,
                       n_boot: int = N_BOOT, mean_block: float = MEAN_BLOCK_MONTHS,
                       seed: int = SEED) -> dict | None:
    """Percentile CI for the mean/median under the stationary block bootstrap.

    Same return shape as farm.stats.bootstrap_ci plus `mean_block`, so
    farm.stats.ci_verdict applies unchanged.
    """
    xs = [float(v) for v in sample if v is not None and v == v]
    n = len(xs)
    if n < fstats.MIN_BOOTSTRAP_N:
        return None
    if stat not in ("median", "mean"):
        raise ValueError(f"block_bootstrap_ci: unsupported statistic {stat!r}")
    a = np.asarray(xs, dtype=float)
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_indices(n, n_boot, mean_block, rng)
    fn = np.median if stat == "median" else np.mean
    boot = fn(a[idx], axis=1)
    alpha = 1.0 - conf
    lo, hi = (float(x) for x in np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0]))
    return {"stat": stat, "n": n, "point": float(fn(a)), "lo": lo, "hi": hi,
            "conf": conf, "n_boot": n_boot, "seed": seed, "mean_block": mean_block,
            "contains_zero": bool(lo <= 0.0 <= hi)}


def newey_west_t(sample, lag: int = NW_LAG) -> dict:
    """HAC t-statistic for H0: mean = 0 (Bartlett kernel, `lag` lags).

    Autocovariances use the 1/n convention: γ_k = Σ_{t>k} d_t d_{t−k} / n with
    d the demeaned series; LRV = γ_0 + 2 Σ_{k=1..L} (1 − k/(L+1)) γ_k;
    se = sqrt(LRV / n). lag=0 is the plain (population-variance) t.
    """
    x = np.asarray([float(v) for v in sample if v is not None and v == v], dtype=float)
    n = len(x)
    if n < 3:
        return {"n": n, "mean": float("nan"), "se": float("nan"), "t": float("nan"), "lag": lag}
    d = x - x.mean()
    L = max(0, min(int(lag), n - 1))
    lrv = float(d @ d) / n
    for k in range(1, L + 1):
        gamma = float(d[k:] @ d[:-k]) / n
        lrv += 2.0 * (1.0 - k / (L + 1.0)) * gamma
    lrv = max(lrv, 0.0)
    se = math.sqrt(lrv / n)
    t = float(x.mean() / se) if se > 0 else float("nan")
    return {"n": n, "mean": float(x.mean()), "se": se, "t": t, "lag": L}


def evaluate_excess(excess, *, n_trials: int) -> dict:
    """All headline numbers for one pooled monthly-excess series."""
    x = np.asarray([float(v) for v in excess], dtype=float)
    n = len(x)
    out = {"n_months": n}
    if n == 0:
        return out
    out["mean"] = float(x.mean())
    out["median"] = float(np.median(x))
    out["beat_rate"] = float((x > 0).mean())
    out["mean_ci"] = block_bootstrap_ci(x, stat="mean")
    out["median_ci"] = block_bootstrap_ci(x, stat="median")
    out["nw"] = newey_west_t(x)
    dsr, sr, sr0 = fstats.deflated_sharpe(x, n_trials=max(1, n_trials))
    out["dsr"] = None if dsr != dsr else float(dsr)
    out["sharpe_monthly"] = None if sr != sr else float(sr)
    out["sharpe_annual"] = None if sr != sr else float(sr * math.sqrt(12))
    out["sr0"] = None if sr0 != sr0 else float(sr0)
    out["n_trials"] = n_trials
    return out


def verdict(ev: dict) -> str:
    """The pre-registered rule from the module docstring. No discretion."""
    if ev.get("n_months", 0) < MIN_MONTHS or not ev.get("median_ci"):
        return "NO-DATA"
    ci, t = ev["median_ci"], ev["nw"]["t"]
    if ci["lo"] > 0 and t >= T_CRIT:
        return "BEATS"
    if ci["hi"] < 0 and t <= -T_CRIT:
        return "TRAILS"
    return "INDISTINGUISHABLE"


# --------------------------------------------------------------------------- #
# loading & pairing
# --------------------------------------------------------------------------- #
def control_of(config_id: str) -> str | None:
    if config_id in CONTROLS:
        return None
    return SPY if config_id in SPY_BOOKS else EW


def registered(result: dict) -> str | None:
    return result.get("registered") or REGISTERED_FALLBACK.get(result["config_id"])


def insample_folds(result: dict, cutoff: str = INSAMPLE_CUTOFF) -> set[int]:
    reg = registered(result)
    return {INSAMPLE_FOLD_INDEX} if reg is not None and reg < cutoff else set()


def _fold_key(f: dict) -> tuple:
    return (f.get("split_date"), f.get("validate_end"))


def fold_monthly(result: dict) -> dict[tuple, list[tuple[str, float]]]:
    """fold key → [(month, return)] from `validate_monthly_equity`; ok folds only."""
    out = {}
    for f in result.get("folds", []):
        pts = f.get("validate_monthly_equity")
        if f.get("status") == "ok" and pts:
            out[_fold_key(f)] = monthly_returns(pts)
    return out


def paired_excess(book: dict, ctrl: dict, *, exclude: set[int]) -> list[dict]:
    """[{month, fold, book, control, excess}] over months both sides report."""
    bm, cm = fold_monthly(book), fold_monthly(ctrl)
    idx_of = {_fold_key(f): f.get("index") for f in book.get("folds", [])}
    rows = []
    for key in sorted(bm):
        if key not in cm or idx_of.get(key) in exclude:
            continue
        c = dict(cm[key])
        for m, r in bm[key]:
            if m in c:
                rows.append({"month": m, "fold": idx_of.get(key), "book": r,
                             "control": c[m], "excess": r - c[m]})
    return rows


def load_results(results_dir: Path = RESULTS_DIR) -> dict[str, dict]:
    out = {}
    for p in sorted(results_dir.glob("*.json")):
        d = json.loads(p.read_text())
        if "config_id" in d and "folds" in d:
            out[d["config_id"]] = d
    return out


def proxy_results(wf: dict[str, dict], bt_dir: Path = BACKTEST_RESULTS_DIR,
                  window: str = "15y") -> dict[str, dict]:
    """Rebuild walk-forward-shaped results from the continuous backtests.

    For each book with a `<book>__<window>.json`, split its `monthly_equity`
    into the frozen folds (a month belongs to fold k when split-month < month ≤
    validate-end-month) and emit one `ok` fold per fold with ≥ 2 points, with
    the month before the first validate month as the base row.
    """
    out = {}
    for cid, r in wf.items():
        p = bt_dir / f"{cid}__{window}.json"
        if not p.exists():
            continue
        bt = json.loads(p.read_text())
        pts = {m: float(e) for m, e in bt.get("monthly_equity", [])}
        months = sorted(pts)
        folds = []
        for f in r["protocol"]["folds"]:
            lo, hi = f["split_date"][:7], f["validate_end"][:7]
            inside = [m for m in months if lo < m <= hi]
            base = [m for m in months if m <= lo]
            if not inside or not base:
                continue
            series = [[m, pts[m]] for m in [base[-1]] + inside]
            folds.append({**f, "status": "ok", "validate_monthly_equity": series,
                          "validate": {"start_date": series[0][0], "end_date": series[-1][0]}})
        out[cid] = {"config_id": cid, "name": r.get("name"), "strategy": r.get("strategy"),
                    "registered": registered(r), "protocol": r["protocol"],
                    "source": f"backtests/results/{p.name}",
                    "fill_model": bt.get("fill_model") or "v1 (unlabelled)",
                    "folds": folds}
    return out


# --------------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------------- #
def build(results: dict[str, dict], *, cutoff: str = INSAMPLE_CUTOFF) -> list[dict]:
    books = [c for c in results if c not in CONTROLS]
    n_trials = len(books)
    rows = []
    for cid in sorted(results):
        r = results[cid]
        ctrl = control_of(cid)
        excl = insample_folds(r, cutoff)
        row = {"config_id": cid, "control": ctrl, "registered": registered(r),
               "excluded_folds": sorted(excl), "source": r.get("source", "walkforward")}
        if ctrl is None:
            row.update({"verdict": "reference", "n_months": 0})
        elif ctrl not in results:
            row.update({"verdict": "NO-CONTROL", "n_months": 0})
        else:
            pairs = paired_excess(r, results[ctrl], exclude=excl)
            ev = evaluate_excess([p["excess"] for p in pairs], n_trials=n_trials)
            row.update(ev)
            row["verdict"] = verdict(ev)
            row["months"] = pairs
        rows.append(row)
    order = {"BEATS": 0, "INDISTINGUISHABLE": 1, "TRAILS": 2, "NO-DATA": 3,
             "NO-CONTROL": 4, "reference": 5}
    rows.sort(key=lambda x: (order.get(x["verdict"], 9), -(x.get("median") or -9e9)))
    return rows


def fold_level_verdicts(readme: Path = WF_DIR / "README.md") -> dict[str, str]:
    """Book → PASS/WATCH/REVIEW/… from the fold-level index table."""
    if not readme.exists():
        return {}
    pat = re.compile(r"^\| \[([a-z0-9_]+)\]\([a-z0-9_]+\.md\) \| ([A-Za-z-]+) \|")
    out = {}
    for line in readme.read_text().splitlines():
        m = pat.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _pct(v) -> str:
    return "·" if v is None or v != v else f"{v * 100:+.2f}%"


def _ci(ci) -> str:
    return "_none_" if not ci else f"[{_pct(ci['lo'])}, {_pct(ci['hi'])}]"


def _num(v, nd=2) -> str:
    return "·" if v is None or v != v else f"{v:+.{nd}f}"


def _table(rows: list[dict]) -> list[str]:
    hdr = ("| Book | Control | Months | Folds dropped | Mean excess/mo | 90% CI (mean) | "
           "Median excess/mo | 90% CI (median) | NW t | DSR | Months beating | Verdict |")
    out = [hdr, "|" + "---|" * 12]
    for r in rows:
        if r["verdict"] in ("reference",):
            out.append(f"| {r['config_id']} | — | · | · | · | · | · | · | · | · | · | reference |")
            continue
        drop = ",".join(str(i) for i in r["excluded_folds"]) or "none"
        out.append(
            f"| {r['config_id']} | {r['control']} | {r.get('n_months', 0)} | {drop} | "
            f"{_pct(r.get('mean'))} | {_ci(r.get('mean_ci'))} | {_pct(r.get('median'))} | "
            f"{_ci(r.get('median_ci'))} | {_num((r.get('nw') or {}).get('t'))} | "
            f"{_num(r.get('dsr'))} | {_pct(r.get('beat_rate'))} | **{r['verdict']}** |")
    return out


def _why(fold_v: str, r: dict) -> str:
    v = r["verdict"]
    if v in ("NO-DATA", "NO-CONTROL"):
        return "no monthly series on disk yet"
    med_ci, mean_ci = r.get("median_ci") or {}, r.get("mean_ci") or {}
    bits = []
    if fold_v == "PASS" and v != "BEATS":
        bits.append("fold PASS keyed on the mean; median monthly CI "
                    + ("straddles 0" if med_ci.get("contains_zero") else "is negative"))
    if fold_v == "REVIEW" and v == "INDISTINGUISHABLE":
        bits.append("monthly median CI straddles 0" if med_ci.get("contains_zero")
                    else f"NW t {_num(r['nw']['t'])} short of ±{T_CRIT}")
    if fold_v == "REVIEW" and v == "TRAILS":
        bits.append("agrees: median and NW t both negative")
    if fold_v == "WATCH" and v == "TRAILS":
        bits.append("120 months resolve what 10 folds could not: negative on both tests")
    if fold_v == "WATCH" and v == "INDISTINGUISHABLE":
        bits.append("agrees; monthly CIs still straddle 0")
    if mean_ci and med_ci and (mean_ci.get("contains_zero") != med_ci.get("contains_zero")):
        side = "left" if (r.get("mean") or 0) < (r.get("median") or 0) else "right"
        bits.append(f"mean and median CIs disagree (mean {'below' if side == 'left' else 'above'} "
                    f"median: heavy {side} tail)")
    return "; ".join(bits) or "—"


def render(rows: list[dict], *, source: str, proxy_rows: list[dict] | None,
           fold_verdicts: dict[str, str], stamp: str) -> str:
    L = []
    L.append(f"# Walk-forward at monthly granularity — {stamp}\n")
    L.append("Generated by `farm/walkforward/monthly.py`. Same replays as the fold-level "
             "report, re-read one month at a time. Nothing here changes a fold-level verdict; "
             "it is the second reading the evaluation asked for.\n")
    L.append("## Rule (pre-registered, mechanical)\n")
    L.append(f"* Unit: paired monthly excess return, book − control, over validate months "
             f"only. Control is `{EW}` for single-name books and `{SPY}` for asset-allocation "
             f"books ({', '.join(sorted(SPY_BOOKS))}).")
    L.append(f"* Fold {INSAMPLE_FOLD_INDEX} (2025-08-28→2026-08-28) is **dropped** for every book "
             f"registered before {INSAMPLE_CUTOFF}: it is the data those rules were written "
             f"against. August-2026 registrations keep it (flagged in `Folds dropped`).")
    L.append(f"* CIs: stationary block bootstrap (Politis-Romano), geometric blocks with mean "
             f"{MEAN_BLOCK_MONTHS} months, {N_BOOT:,} draws, seed {SEED}, {int(CONF * 100)}% "
             f"two-sided, on the mean and on the median.")
    L.append(f"* NW t: Newey-West t on the mean, Bartlett kernel, {NW_LAG} lags.")
    L.append(f"* DSR: farm.stats.deflated_sharpe on the pooled months, n_trials = number of "
             f"books in the table (fallback variance); bar {DSR_BAR}. Context only.")
    L.append(f"* **BEATS** = median CI entirely > 0 AND NW t ≥ +{T_CRIT}. **TRAILS** = median CI "
             f"entirely < 0 AND NW t ≤ −{T_CRIT}. Otherwise **INDISTINGUISHABLE**; fewer than "
             f"{MIN_MONTHS} months = **NO-DATA**. Median carries the verdict (the fold PASS "
             f"keyed on a mean one fold could hijack); the NW t on the mean is required "
             f"corroboration.\n")
    L.append("## 1. Walk-forward replays (fill model v2, ten independent fold replays)\n")
    have = [r for r in rows if r.get("n_months", 0) > 0]
    if not have:
        L.append("**No monthly series exists on disk for any book.** The fold JSONs written "
                 "before 2026-09-02 carry summary statistics only. `runner.run_fold` now "
                 "persists `validate_monthly_equity` per fold; this table fills in after the "
                 "next weekly walk-forward (Sunday). Section 2 is the proxy until then.\n")
    else:
        L.append(f"Source: `{source}`.\n")
    L.extend(_table(rows))
    L.append("")
    if proxy_rows is not None:
        L.append("## 2. Proxy — continuous 15-year backtests, cut into the same folds\n")
        L.append("**Read this as a proxy, not the walk-forward.** One continuous replay per book "
                 "(`data/reports/backtests/results/<book>__15y.json`, fill model v1, "
                 "2011-07→2026-07-16) rather than ten fold replays that each restart from cash; "
                 "the monthly equity is split at the frozen protocol's fold dates and only "
                 "validate months (2016-09 onward) are paired. Same controls, same fold-10 rule "
                 "(the proxy ends 2026-07 anyway, so fold 10 is at most 11 partial months). "
                 "Books without a 15y backtest are absent. Weekly/monthly-rebalanced screen "
                 "books have little state, so their proxy months should track the fold replays "
                 "closely; the daily-stop and breakout books (`momo_stopped`, "
                 "`turtle_breakout`, `mr_overlay*`) carry more path dependence.\n")
        L.extend(_table(proxy_rows))
        L.append("")
    L.append("## 3. Monthly verdict vs fold-level PASS / WATCH / REVIEW\n")
    cmp_rows = proxy_rows if (proxy_rows and not have) else rows
    basis = "proxy (section 2)" if cmp_rows is proxy_rows else "walk-forward (section 1)"
    L.append(f"Monthly verdict basis: {basis}. Fold-level verdict from "
             f"`data/reports/walkforward/README.md`.\n")
    L.append("| Book | Fold-level | Monthly | Changed? | Why |")
    L.append("|---|---|---|---|---|")
    changed = 0
    for r in cmp_rows:
        if r["verdict"] == "reference":
            continue
        fv = fold_verdicts.get(r["config_id"], "·")
        same = {("PASS", "BEATS"), ("REVIEW", "TRAILS"), ("WATCH", "INDISTINGUISHABLE")}
        ch = "·" if r["verdict"] in ("NO-DATA", "NO-CONTROL") else \
            ("no" if (fv, r["verdict"]) in same else "**yes**")
        changed += ch == "**yes**"
        L.append(f"| {r['config_id']} | {fv} | {r['verdict']} | {ch} | {_why(fv, r)} |")
    L.append("")
    L.append(f"{changed} book(s) change reading. Mapping used for 'same': PASS↔BEATS, "
             f"WATCH↔INDISTINGUISHABLE, REVIEW↔TRAILS.\n")
    return "\n".join(L)


def write_report(*, results_dir: Path = RESULTS_DIR, out_dir: Path = WF_DIR,
                 bt_dir: Path = BACKTEST_RESULTS_DIR, stamp: str | None = None,
                 with_proxy: bool = True, readme: Path | None = None) -> tuple[Path, Path]:
    stamp = stamp or date.today().isoformat()
    wf = load_results(results_dir)
    rows = build(wf)
    proxy = build(proxy_results(wf, bt_dir)) if with_proxy else None
    fv = fold_level_verdicts(readme or (out_dir / "README.md"))
    md = render(rows, source=str(results_dir), proxy_rows=proxy, fold_verdicts=fv, stamp=stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"monthly-{stamp}.md"
    js_path = out_dir / f"monthly-{stamp}.json"
    md_path.write_text(md)
    payload = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "rule": {"mean_block_months": MEAN_BLOCK_MONTHS, "nw_lag": NW_LAG,
                        "n_boot": N_BOOT, "seed": SEED, "conf": CONF, "t_crit": T_CRIT,
                        "min_months": MIN_MONTHS, "insample_cutoff": INSAMPLE_CUTOFF,
                        "insample_fold": INSAMPLE_FOLD_INDEX, "spy_books": sorted(SPY_BOOKS)},
               "fold_level_verdicts": fv, "walkforward": rows, "proxy": proxy}
    js_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return md_path, js_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--out-dir", default=str(WF_DIR))
    ap.add_argument("--backtests-dir", default=str(BACKTEST_RESULTS_DIR))
    ap.add_argument("--stamp", default=None, help="YYYY-MM-DD in the file name (default today)")
    ap.add_argument("--no-proxy", action="store_true",
                    help="skip section 2 (continuous-backtest proxy)")
    a = ap.parse_args()
    md, js = write_report(results_dir=Path(a.results_dir), out_dir=Path(a.out_dir),
                          bt_dir=Path(a.backtests_dir), stamp=a.stamp,
                          with_proxy=not a.no_proxy)
    print(md)
    print(js)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
