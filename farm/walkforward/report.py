#!/usr/bin/env python
"""Render data/reports/walkforward/ from whatever per-book results exist.

Pure function of `data/reports/walkforward/results/*.json` — every job rewrites
the reports when it finishes, so the tables fill in as the weekly grid drains
and a partially-drained grid is still a readable, honestly-labelled report. The
reports ride `engine/sync.py`'s `git add data/`, like the backtest and
experiment reports.

The DISCLOSURES block is emitted at the top of every file. A walk-forward on a
survivor universe with a static cap filter can look like evidence when it is
mostly bookkeeping, and the comparison that strips most of that out is
vs-EW-on-the-same-universe, fold by fold.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine.lib.settings import DATA_DIR, REPO_ROOT  # noqa: F401
from farm import stats as fstats

WF_DIR = DATA_DIR / "reports" / "walkforward"
RESULTS_DIR = WF_DIR / "results"

EW = "ew_benchmark"
SPY = "spy_benchmark"
BENCHMARKS = (EW, SPY)

LEAGUE_INCEPTION = "2026-07-17"

DISCLOSURES = """\
## Disclosures — read before any number below

1. **Survivor universe, and it is NOT a constant.** `prices` holds only tickers
   listed TODAY, so every name delisted, acquired or bankrupted inside a fold is
   absent entirely. The house lesson has priced this at roughly **+7pp/yr of fake
   return** for a screen-driven book — but that flat figure is wrong in SHAPE, and
   the `Universe` column on every fold table below exists to show it. Measured
   2026-08-20 against World Bank listed-company counts, the store covers
   **~11% of the companies that existed in 1996, ~24% in 2003 and ~42% in 2014**
   (ex-ETF). The bias therefore grows monotonically as a window moves back, and an
   early fold rests on a thinner, more winner-selected cross-section than a late
   one. Not one 2008 casualty is present: LEH, BSC, ENE, WCOM, CFC, MER, SIVB and
   FRC are all absent, so **a fold spanning 2008 is one in which those names cannot
   lose money.** That is WHY the headline comparison here is **vs EW (same
   universe, same screen), fold by fold** — the bias is largely common to both
   sides of that difference. Absolute return is context, not evidence, and a fold
   with a small `Universe` count deserves proportionally less weight.
2. **Out-of-sample in the DATA, not in the RULE.** Each validate window is data
   the preceding train window never saw, and nothing is fitted anywhere in this
   workload (see D-WF5). But these books were written by a human who has lived
   through this market, so a validate window from 2021 is not evidence the rule
   would have been *chosen* in 2020. **The league's live forward record remains
   the only true out-of-sample evidence.** This report answers a narrower and
   still useful question: *is the rule behaving now the way it behaved on the
   sessions immediately before, and against the same benchmark?*
3. **`low_vol` uses TODAY's fundamentals snapshot.** No historical market caps
   exist (first snapshot 2026-07-18), so its "$5B+" filter is the current cap
   list restamped to the window start — a static-cap look-ahead, disclosed.
4. **The newest validate window overlaps the live league.** The anchor is the
   latest session in the store (D-WF3), and the league went live
   """ + LEAGUE_INCEPTION + """. Sessions after that date are a *shadow* of the
   live book — the same rule re-run on the same bars — not independent evidence.
   The overlap is a few weeks against a 12-month window today, and it is
   labelled per fold below.
5. **Every fold restarts at the reference notional** (D-WF2), so folds are
   comparable to each other and a book cannot be flattered or crippled by what
   an account did years earlier. Fold returns therefore do NOT compound into
   the multi-year number a single continuous replay would give — that number is
   the historical-backtest farm's job (`data/reports/backtests/`).
6. **Books that cannot be replayed are absent, not zero.** See the exclusions
   list at the bottom. Nothing is faked to fill a row.
"""

VERDICT_RULE = """\
**Verdict rule (pre-registered, mechanical, and NOT an automatic kill).** For
each book, against `ew_benchmark` on the same folds:

* **PASS** — beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0.
* **WATCH** — exactly one of those two fails.
* **REVIEW** — both fail *and* the latest validate window also trails EW.

REVIEW means the book goes on the Sunday review agenda against its own
pre-registered kill criterion (printed on its page). The prose criterion
decides; this flag only decides what gets read. Benchmarks are not judged.
"""

# The rule above is FROZEN. What follows is an error bar printed BESIDE it.
INTERVAL_NOTE = """\
**The interval is new information, not a new rule (added 2026-08-20).** The
PASS / WATCH / REVIEW rule above is unchanged: it still reads the beat rate and
the *mean* excess exactly as it was pre-registered, and no verdict in this
report has been recomputed, softened or overridden by an interval. What is new
is the **90% bootstrap CI on mean excess vs EW** in the column beside it, and a
mechanical `INDISTINGUISHABLE` label for any book whose interval contains 0.

Read the two together: a **PASS whose interval straddles zero is a PASS on a
number this evidence cannot separate from the benchmark**, and a REVIEW whose
interval straddles zero is not proof the book is broken either. The verdict says
what gets read on Sunday. The interval says how much the number underneath it
is worth.

**Method.** Percentile bootstrap over FOLDS, {draws:,} resamples, fixed seed
`{seed}` so the report re-renders identically from unchanged inputs. Folds are
the resampling unit because each is an independent replay from the reference
notional (D-WF2) over a validate window no other fold's validate window touches
(D-WF1). Folds with status other than `ok` — including `inert`, a book that
placed zero fills — are excluded before resampling; an inert fold is not
evidence. Fewer than {min_n} comparable folds gets **no interval**, printed as
`·`, never a zero.

**Caveat that cuts against us.** Adjacent folds share twelve months of TRAIN
window (train 24mo, step 12mo) and all folds come from one market history, so an
i.i.d. bootstrap UNDERSTATES the true uncertainty. These intervals are a floor
on the error bar. At 10 folds the bootstrap can reject a large effect and cannot
confirm a small one; methods that could (block or stationary bootstrap) need a
fold count in the high tens and are deliberately not used here.
""".format(draws=fstats.BOOTSTRAP_DRAWS, seed=fstats.BOOTSTRAP_SEED,
           min_n=fstats.MIN_BOOTSTRAP_N)


# --------------------------------------------------------------------------- #
def load_results(results_dir: Path = RESULTS_DIR) -> list[dict]:
    if not results_dir.exists():
        return []
    out = []
    for p in sorted(results_dir.glob("*.json")):
        try:
            out.append(_relabel_stale_inert(json.loads(p.read_text())))
        except json.JSONDecodeError:
            print(f"[wf-report] skipping unreadable {p}")
    return out


def _relabel_stale_inert(r: dict) -> dict:
    """Apply the runner's inert guard to results written BEFORE it existed.

    `runner.run_fold` has returned `status: "inert"` for a zero-fill fold since
    2026-08-20, but every result JSON on disk from before that date still says
    `"ok"` with `n_fills: 0` — `earnings_context_pead` is the known one, and it
    is the row that got published as `+0.00% mean validate / −30.55% vs EW /
    REVIEW`. Re-reading those files without re-labelling would keep that row in
    the table, and it would now carry a bootstrap CI as well: an error bar
    around a number that was never a measurement, which is worse than the point
    estimate alone. The guard belongs at the measurement layer wherever the
    measurement is read, and re-running twenty-two replays to fix a label is not
    the honest cost here. Only an exact 0 triggers it; a fold whose JSON has no
    `n_fills` key at all is left alone rather than guessed at.
    """
    for f in r.get("folds", []):
        if f.get("status") == "ok" and f.get("n_fills") == 0:
            f["status"] = "inert"
            f["reason"] = ("0 fills over the whole fold — the book never traded, "
                           "so its flat equity is not a result (re-labelled at "
                           "report time; this result predates the runner guard)")
    if any(f.get("status") == "inert" for f in r.get("folds", [])):
        if __package__:
            from . import runner as _runner
        else:  # pragma: no cover
            from farm.walkforward import runner as _runner
        r["summary"] = _runner.summarize(r["folds"])
    return r


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{'+' if v >= 0 else '−'}{abs(v) * 100:.2f}%"


def _num(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{'+' if v >= 0 else '−'}{abs(v):.2f}"


def _rate(v) -> str:
    """A hit rate — a share of folds, never a signed return."""
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{v * 100:.0f}%"


def _fold_key(f: dict) -> tuple:
    """Folds match across books only if their windows are literally the same."""
    return (f.get("split_date"), f.get("validate_end"))


def _bench_index(results: list[dict]) -> dict[str, dict[tuple, dict]]:
    out: dict[str, dict[tuple, dict]] = {}
    for r in results:
        if r["config_id"] in BENCHMARKS:
            out[r["config_id"]] = {_fold_key(f): f for f in r["folds"]
                                   if f.get("status") == "ok"}
    return out


def _excess(fold: dict, bench: dict[tuple, dict] | None):
    if not bench:
        return None
    b = bench.get(_fold_key(fold))
    a = fold.get("validate", {}).get("total_return")
    if b is None or a is None:
        return None
    bv = b.get("validate", {}).get("total_return")
    return None if bv is None else a - bv


def book_verdict(r: dict, bench: dict[str, dict[tuple, dict]]) -> tuple[str, dict]:
    """(verdict, measured numbers) per the pre-registered rule above."""
    ok = [f for f in r["folds"] if f.get("status") == "ok"]
    ew = bench.get(EW)
    exc = [(_excess(f, ew)) for f in ok]
    exc = [e for e in exc if e is not None]
    # The CI is on the MEAN excess, because the mean is the quantity the frozen
    # verdict rule reads. Interval-ing the median here would be adding an error
    # bar to a statistic no verdict uses — informative-looking and misaligned.
    ci = fstats.bootstrap_ci(exc, stat="mean")
    stats = {
        "n_compared": len(exc),
        "beat_rate": (sum(1 for e in exc if e > 0) / len(exc)) if exc else None,
        "mean_excess": (sum(exc) / len(exc)) if exc else None,
        "latest_excess": exc[-1] if exc else None,
        "mean_excess_ci": ci,
        "distinguishable": fstats.ci_verdict(ci),
    }
    if r["config_id"] in BENCHMARKS:
        return "reference", stats
    if not exc:
        return "no-benchmark", stats
    beats = stats["beat_rate"] >= 0.5
    positive = stats["mean_excess"] >= 0
    if beats and positive:
        return "PASS", stats
    if not beats and not positive and stats["latest_excess"] < 0:
        return "REVIEW", stats
    return "WATCH", stats


# --------------------------------------------------------------------------- #
FOLD_HEADER = ("| Fold | Train window | Train ret | Train CAGR | Validate window | "
               "Validate ret | CAGR | Vol | Sharpe | Max DD | vs EW | vs SPY | "
               "Fills | Universe |")
FOLD_RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def _fold_row(f: dict, bench: dict[str, dict[tuple, dict]]) -> str:
    if f.get("status") != "ok":
        return (f"| {f.get('index')} | {f.get('train_start')}→{f.get('split_date')} "
                f"| — | — | {f.get('split_date')}→{f.get('validate_end')} | "
                f"**{f.get('status')}**: {f.get('reason', '')} | | | | | | | | |")
    t, v = f["train"], f["validate"]
    flag = " ⚑" if f.get("train_start_clamped_to_data_floor") else ""
    overlap = " ◈" if (f.get("validate", {}).get("end_date") or "") > LEAGUE_INCEPTION \
        else ""
    return (f"| {f['index']}{flag}{overlap} | {t.get('start_date')}→{t.get('end_date')} "
            f"| {_pct(t.get('total_return'))} | {_pct(t.get('cagr'))} "
            f"| {v.get('start_date')}→{v.get('end_date')} "
            f"| **{_pct(v.get('total_return'))}** | {_pct(v.get('cagr'))} "
            f"| {_pct(v.get('vol_ann'))} | {_num(v.get('sharpe'))} "
            f"| {_pct(v.get('max_dd'))} | {_pct(_excess(f, bench.get(EW)))} "
            f"| {_pct(_excess(f, bench.get(SPY)))} | {f.get('n_validate_fills')} "
            f"| {_num_int(f.get('validate_universe'))} |")


def _num_int(v) -> str:
    """Fold universe size — '·' when the run predates the field, never 0.
    A missing measurement is not a measurement of zero."""
    return "·" if v is None else f"{int(v):,}"


SUMMARY_HEADER = ("| Book | Verdict | Distinguishable from EW? | Folds | "
                  "Validate win rate | Beats EW | Mean validate | "
                  "Mean excess vs EW | 90% CI on mean excess | Latest validate | "
                  "Latest vs EW | Mean decay (CAGR) | Worst validate DD |")
SUMMARY_RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def _ci_cell(ci: dict | None) -> str:
    """No interval is printed as an absence. A zero-filled CI would be a claim."""
    if ci is None:
        return "·"
    return f"[{_pct(ci['lo'])}, {_pct(ci['hi'])}]"


def _distinguishable_cell(v: str, is_reference: bool) -> str:
    """Loud on purpose: for most books this is the honest headline and it must
    not be readable as a footnote next to a bold verdict."""
    if is_reference:
        return "—"
    if v == "INDISTINGUISHABLE":
        return "**INDISTINGUISHABLE**"
    if v == "NO-CI":
        return "_no interval_"
    return f"**{v}**"


def _summary_row(r: dict, verdict: str, vs: dict) -> str:
    s = r["summary"]
    ref = r["config_id"] in BENCHMARKS
    return (f"| [{r['config_id']}]({r['config_id']}.md) | {verdict} "
            f"| {_distinguishable_cell(vs.get('distinguishable', 'NO-CI'), ref)} "
            f"| {s.get('n_folds_ok')} | {_rate(s.get('validate_win_rate'))} "
            f"| {_rate(vs.get('beat_rate'))} | {_pct(s.get('mean_validate_total'))} "
            f"| {_pct(vs.get('mean_excess'))} | {_ci_cell(vs.get('mean_excess_ci'))} "
            f"| {_pct(s.get('latest_validate_total'))} "
            f"| {_pct(vs.get('latest_excess'))} | {_pct(s.get('mean_decay_cagr'))} "
            f"| {_pct(s.get('worst_validate_max_dd'))} |")


VERDICT_ORDER = {"REVIEW": 0, "WATCH": 1, "PASS": 2, "no-benchmark": 3,
                 "reference": 4}


def write_reports(results_dir: Path = RESULTS_DIR,
                  out_dir: Path = WF_DIR) -> list[Path]:
    results = load_results(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    bench = _bench_index(results)
    written: list[Path] = []

    proto = results[0]["protocol"] if results else None
    proto_line = ("_no results yet_" if not proto else
                  f"**train {proto['train_months']}mo → validate "
                  f"{proto['validate_months']}mo, step {proto['step_months']}mo, "
                  f"{proto['n_folds']} folds, anchored {proto['anchor']}**")

    # ---- index ----------------------------------------------------------- #
    lines = [
        "# Walk-forward re-validation of the active league rules",
        "",
        f"_{len(results)} book(s) re-validated · protocol {proto_line} · "
        f"generated {stamp}._",
        "",
        "Every book below is replayed by its OWN live strategy code through the "
        "real `sim/league.py` day-step — real orders, real t+1-open fills with "
        "the league's slippage and liquidity guards, real dividend crediting. "
        "The config replayed is the JSON frozen in the live `portfolios` row "
        "(D-WF4), i.e. the rule the league is actually trading. Nothing is "
        "reimplemented for this report and no bar is ever invented.",
        "",
        "This is the input to the **Sunday review loop** (execution design §6): "
        "changes are made at reviews, one at a time, justified by walk-forward "
        "evidence rather than last week's P&L.",
        "",
        DISCLOSURES,
        "",
        VERDICT_RULE,
        "",
        INTERVAL_NOTE,
        "",
        "⚑ = the fold's train window was clamped to the book's data floor. "
        "◈ = the validate window extends past league inception "
        f"({LEAGUE_INCEPTION}) and so partly shadows the live record.",
        "",
        "## Summary — all books, all folds",
        "",
    ]
    # A book with no `ok` fold has no measurement, only an absence. Disclosure 6
    # says such a book is "absent, not zero" — before 2026-08-20 that was not
    # true: `earnings_context_pead` placed 0 fills in all 6 folds and was
    # published as +0.00% mean validate, −30.55% excess and a REVIEW verdict.
    # Inert books are split out here and named in the exclusions section.
    inert = [r for r in results if not (r["summary"].get("n_folds_ok") or 0)]
    results = [r for r in results if (r["summary"].get("n_folds_ok") or 0)]

    if results:
        rows = []
        n_judged = n_indistinct = 0
        for r in results:
            verdict, vs = book_verdict(r, bench)
            if r["config_id"] not in BENCHMARKS and vs.get("distinguishable"):
                n_judged += 1
                n_indistinct += vs["distinguishable"] == "INDISTINGUISHABLE"
            rows.append((VERDICT_ORDER.get(verdict, 9),
                         -(r["summary"].get("mean_validate_total") or 0),
                         _summary_row(r, verdict, vs)))
        if n_judged:
            lines += [f"**{n_indistinct} of {n_judged} judged book(s) are "
                      f"`INDISTINGUISHABLE` from `ew_benchmark`** at 90% "
                      f"confidence on mean excess. Read every verdict in the "
                      f"next column with that column beside it.", ""]
        lines += [SUMMARY_HEADER, SUMMARY_RULE] + [x[2] for x in sorted(rows)]
    else:
        lines.append("_No book has been re-validated yet._")
    lines.append("")

    # ---- the latest fold, side by side ----------------------------------- #
    if results:
        # The newest window ANY book reached — books whose data floor dropped
        # early folds still share the recent ones, so take the max, not the
        # first book's last.
        keys = [_fold_key(f) for r in results for f in r["folds"]
                if f.get("status") == "ok"]
        latest_key = max(keys) if keys else None
        if latest_key:
            lines += [
                f"## Latest validate window ({latest_key[0]} → {latest_key[1]})",
                "", FOLD_HEADER.replace("| Fold |", "| Book |"), FOLD_RULE]
            latest_rows = []
            for r in results:
                for f in r["folds"]:
                    if f.get("status") == "ok" and _fold_key(f) == latest_key:
                        row = _fold_row(f, bench)
                        parts = row.split("|")
                        parts[1] = f" {r['config_id']} "
                        latest_rows.append((
                            -(f["validate"].get("total_return") or -9e9),
                            "|".join(parts)))
            lines += [x[1] for x in sorted(latest_rows)]
            lines.append("")

    # ---- exclusions ------------------------------------------------------ #
    if __package__:
        from . import protocol as _proto
    else:  # pragma: no cover
        from farm.walkforward import protocol as _proto
    lines += ["## Books NOT walk-forwarded", ""]
    for cid, why in _proto.EXCLUDED.items():
        lines.append(f"* **{cid}** — {why}")
    for r in inert:
        n_inert = r["summary"].get("n_folds_inert") or 0
        lines.append(
            f"* **{r['config_id']}** — INERT: 0 fills in {n_inert} fold(s). The "
            f"book replayed without error and never traded, so it has no return, "
            f"no drawdown and no verdict. Usually a config the strategy can never "
            f"satisfy — check its params before reading anything into it.")
    lines += ["",
              "## How this is produced", "",
              "```sh",
              "# enumerate / enqueue the weekly grid (one job per active book)",
              ".venv/bin/python -m farm.walkforward.grid --list",
              ".venv/bin/python -m farm.walkforward.grid --enqueue",
              ".venv/bin/python -m engine.queue_runner --run",
              "```", "",
              "Intended cadence: **Sunday**, ahead of the weekly review. The "
              "weekday nightly (`engine/run_daily.sh`, cron `30 22 * * 1-5`) "
              "never runs on a Sunday, so this workload is enqueued by its own "
              "cron entry rather than by the nightly — see BUILDLOG.", ""]

    md = out_dir / "README.md"
    md.write_text("\n".join(lines))
    written.append(md)

    # ---- per book -------------------------------------------------------- #
    for r in results:
        verdict, vs = book_verdict(r, bench)
        p = r["protocol"]
        b = [
            f"# {r['name']} — walk-forward re-validation",
            "",
            f"_`{r['config_id']}` · {r['strategy']} · {r.get('cadence')} cadence "
            f"· verdict **{verdict}** · generated "
            f"{r.get('generated_utc')}_",
            "",
            f"**Protocol.** train {p['train_months']}mo → validate "
            f"{p['validate_months']}mo, step {p['step_months']}mo, "
            f"{p['n_folds']} fold(s), anchored {p['anchor']}. Each fold is an "
            f"independent replay starting at ${r.get('initial_cash', 0):,.0f}. "
            f"Span {r.get('span_start')} → {r.get('span_end')} "
            f"({r.get('sessions')} sessions); data floor {r.get('data_floor')}; "
            f"screen source `{r.get('screen_source')}`"
            + (f" ({r.get('screen_rows'):,} passing rows)"
               if r.get("screen_rows") else "") + ".",
            "",
            "**Pre-registered expectation.** " + (r.get("expectation") or "—"),
            "",
            "**Pre-registered kill criterion.** " + (r.get("kill_criterion") or "—"),
            "",
            f"**Measured against `{EW}` on the same folds:** beats it in "
            f"{_rate(vs.get('beat_rate'))} of {vs.get('n_compared')} window(s), "
            f"mean excess {_pct(vs.get('mean_excess'))}, latest "
            f"{_pct(vs.get('latest_excess'))} → **{verdict}**.",
            "",
            f"**90% CI on mean excess vs `{EW}`:** "
            f"{_ci_cell(vs.get('mean_excess_ci'))} → "
            f"{_distinguishable_cell(vs.get('distinguishable', 'NO-CI'), r['config_id'] in BENCHMARKS)}. "
            f"The verdict above is unchanged by this interval — see the note "
            f"below the fold table.",
            "",
            DISCLOSURES,
            "",
            "## Folds", "", FOLD_HEADER, FOLD_RULE,
        ]
        b += [_fold_row(f, bench) for f in r["folds"]]
        for d in r.get("dropped_folds", []):
            b.append(f"| {d.get('index')} | {d.get('train_start')}→"
                     f"{d.get('split_date')} | — | — | {d.get('split_date')}→"
                     f"{d.get('validate_end')} | **dropped**: "
                     f"{d.get('reason', '')} | | | | | | | |")
        s = r["summary"]
        b += [
            "",
            "## Summary", "",
            f"* validate windows: **{s.get('n_folds_ok')}**, "
            f"win rate **{_rate(s.get('validate_win_rate'))}**",
            f"* mean validate return **{_pct(s.get('mean_validate_total'))}** "
            f"(median {_pct(s.get('median_validate_total'))}, "
            f"worst {_pct(s.get('worst_validate_total'))}, "
            f"best {_pct(s.get('best_validate_total'))})",
            f"* mean validate CAGR **{_pct(s.get('mean_validate_cagr'))}** vs mean "
            f"train CAGR {_pct(s.get('mean_train_cagr'))} → decay "
            f"**{_pct(s.get('mean_decay_cagr'))}**",
            f"* mean validate Sharpe {_num(s.get('mean_validate_sharpe'))}, "
            f"worst validate max drawdown {_pct(s.get('worst_validate_max_dd'))}",
            f"* {s.get('total_validate_fills')} fill(s) inside validate windows",
            f"* runtime {r.get('runtime_s')}s "
            f"(scratch {r.get('scratch_s')}s, screen {r.get('screen_s')}s)",
            "",
            VERDICT_RULE,
            "",
            INTERVAL_NOTE,
            "",
        ]
        f = out_dir / f"{r['config_id']}.md"
        f.write_text("\n".join(b))
        written.append(f)

    # --- inert books get an honest page, not a stale one -------------------
    # Filtering inert books out of `results` keeps them off the summary table,
    # but it also means their OLD page is never regenerated. On 2026-08-20 that
    # left `earnings_context_pead.md` on disk still reading "verdict **REVIEW**
    # … mean excess −30.55%" beside a README that had just declared the same run
    # not a measurement. Deleting the page would break the README's own link, so
    # it is REWRITTEN to say what is true.
    for r in inert:
        s_ = r.get("summary", {})
        n_inert = s_.get("n_folds_inert") or 0
        page = [
            f"# {r.get('name', r['config_id'])} — walk-forward re-validation",
            "",
            f"_`{r['config_id']}` · {r.get('strategy', '·')} · "
            f"{r.get('cadence', '·')} cadence · verdict **INERT — no result** · "
            f"generated {r.get('generated_utc', '·')}_",
            "",
            "## This book placed no trades, so it has no result",
            "",
            f"The replay ran without error across **{n_inert} fold(s)** and the "
            f"book posted **zero fills** in every one of them. Its equity "
            f"therefore sat at the reference notional for the whole span, and "
            f"every statistic derived from that curve — return, drawdown, "
            f"Sharpe, excess versus any benchmark — is an artefact of the book "
            f"never trading, not a measurement of the rule.",
            "",
            "**There is no verdict here and there should not be one.** A number "
            "computed over a flat line is not evidence, and this page previously "
            "carried one. Usually the cause is a config the strategy can never "
            "satisfy, or a strategy whose inputs do not exist over the replay "
            "window — check the params and the data floor before reading "
            "anything into this book.",
            "",
            "See the exclusions section of [README.md](README.md).",
            "",
        ]
        f = out_dir / f"{r['config_id']}.md"
        f.write_text("\n".join(page))
        written.append(f)

    print(f"[wf-report] wrote {len(written)} file(s) to {out_dir}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the walk-forward reports.")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--out-dir", default=str(WF_DIR))
    a = ap.parse_args()
    for f in write_reports(Path(a.results_dir), Path(a.out_dir)):
        print(f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
