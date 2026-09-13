#!/usr/bin/env python
"""Render data/reports/backtests/ from whatever replay results exist.

Pure function of `data/reports/backtests/results/*.json` — every replay job
rewrites the reports when it finishes, so the tables fill in as the grid drains
and a partial grid is still a readable (and honestly labelled) report. The
reports ride `engine/sync.py`'s `git add data/`, like the experiment reports.

The DISCLOSURES block is not decoration and is emitted at the top of every file:
a survivor-universe backtest with a static cap filter can look spectacular for
reasons that have nothing to do with the strategy, and the only comparison that
strips most of that out is vs-EW-on-the-same-universe.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from engine.lib import resources
from engine.lib.log import get_logger
from engine.lib.provenance import runtime_source_hash
from engine.lib.settings import DATA_DIR, REPO_ROOT  # noqa: F401
from engine.lib.util import num, pct

log = get_logger("backtest-report")

BACKTEST_DIR = DATA_DIR / "reports" / "backtests"
RESULTS_DIR = BACKTEST_DIR / "results"

WINDOW_ORDER = ["6mo", "1y", "3y", "5y", "15y", "max"]
EW = "ew_benchmark"
SPY = "spy_benchmark"

DISCLOSURES = """\
## Disclosures — read before any number below

1. **Survivor universe.** `prices` holds only tickers listed TODAY, so every
   name that was delisted, acquired or bankrupted inside a window is absent
   entirely. The house lesson prices this at roughly **+7pp/yr of fake return**
   for a screen-driven book. That is WHY the primary comparison here is
   **vs EW (same universe, same screen)** — the bias is largely common to both
   sides of that difference. Absolute CAGR is context, not evidence.
   Two measurements of the size of the problem, both taken while building this:
   (i) re-screening **2026-07-15** today drops 6 names that were in the live
   universe that day — SBIL, NSA, NOWL, AVNS, TMHC, CCRN — the survivor filter
   visibly at work over *two weeks*; (ii) the screen's eligible universe in
   **July 2011** is **1,237 names against 3,873 today**, and every one of those
   1,237 is a name that was still listed in 2026. The 2011 cross-section is not
   the 2011 market; it is the part of the 2011 market that survived.
2. **In-sample context, not out-of-sample evidence.** These configs are the
   league's pre-registered books, replayed as written — one variant per book, no
   sweep, nothing fitted here. But they were chosen by a human who has seen this
   market, so the whole table is labelled **IN-SAMPLE-CONTEXT**. *The league's
   live forward record is the only out-of-sample evidence*, exactly as the E1
   report says.
3. **`low_vol` uses TODAY'S fundamentals snapshot.** No historical market caps
   exist (first snapshot 2026-07-18), so the "$5B+" filter is the current cap
   list restamped to the window start — a static-cap look-ahead, disclosed.
4. **`pead_ear` is absent, not zero.** `earnings_calendar` only spans
   2026-04→2026-10, so its entry signal cannot be computed historically. Its
   forward record is the only record it has. Nothing was faked to fill the row.
5. **`discretionary` is absent** — it is a human book with no code to replay.
6. **Post-calendar-fix semantics throughout.** `momo_stopped` / `mr_overlay` /
   `turtle_breakout` run the current (post calendar-fix) code, so `mr_overlay`
   holds up to its full 10-session time stop here, unlike its pre-fix live record.
7. **Dividends depend on `corporate_actions` completeness** — the row count in
   force for each replay is recorded in its result JSON (`corporate_actions_
   dividend_rows`). A thin actions table degrades a total return toward a price
   return, which is the conservative direction, never an invented distribution.
8. **Windows end 2026-07-16**, the session before league inception. Nothing
   after that date is read, so the farm and the live forward record do not
   overlap.
9. **Costs are the league's own named execution profile**, serialized in every
   result: t+1-open fills, explicit spread/adverse/impact/fee assumptions, a
   profile-defined median-dollar-volume ceiling, no same-bar fills and no
   fabricated bars. `baseline_v1` is the historical
   `max(half_spread, 5) + 5` bp-per-side model.
"""


def load_results(results_dir: Path = RESULTS_DIR) -> list[dict]:
    if not results_dir.exists():
        return []
    eligible = set(EXPECTED_GRID) | set(RETAINED_RESULTS)
    out = []
    for p in sorted(results_dir.glob("*.json")):
        try:
            result = json.loads(p.read_text())
            if (result.get("config_id"), result.get("window")) in eligible:
                out.append(result)
        except json.JSONDecodeError:
            log.warning(f"[backtest-report] skipping unreadable {p}")
    return out


# Report convention: typographic minus, "·" for a missing measurement.
_pct = partial(pct, minus="−")
_num = partial(num, signed=True, minus="−")


def _complete_cohort(r: dict) -> bool:
    """Whether an artifact has every assumption needed for relative evidence."""
    profile = r.get("execution_profile")
    snapshot = r.get("data_snapshot")
    return bool(
        r.get("source_sha256")
        and r.get("fill_model")
        and r.get("universe_policy")
        and r.get("initial_cash") is not None
        and isinstance(profile, dict) and profile
        and isinstance(snapshot, dict) and snapshot.get("sha256")
    )


def _is_comparable(r: dict, benchmark: dict | None) -> bool:
    return bool(
        benchmark
        and _complete_cohort(r)
        and _complete_cohort(benchmark)
        and _cohort_signature(benchmark) == _cohort_signature(r)
        and benchmark.get("data_quality_class") == r.get("data_quality_class")
    )


def _row(r: dict, bench: dict[str, dict]) -> str:
    ew = bench.get(EW)
    spy = bench.get(SPY)
    quality = r.get("data_quality_class") or "legacy_unclassified"
    vs_ew = (None if not _is_comparable(r, ew) or r.get("total_return") is None
             or ew.get("total_return") is None
             else r["total_return"] - ew["total_return"])
    vs_spy = (None if not _is_comparable(r, spy) or r.get("total_return") is None
              or spy.get("total_return") is None
              else r["total_return"] - spy["total_return"])
    if r["config_id"] in (EW, SPY):
        comparison = "reference"
    elif vs_ew is None and vs_spy is None:
        comparison = "**uncontrolled absolute simulation**"
    else:
        comparison = "cohort-matched"
    span = f"{r.get('start_date')}→{r.get('end_date')}"
    flag = " ⚑" if r.get("clamped_to_data_floor") else ""
    return (f"| {r['config_id']}{flag} | `{quality}` | {span} | "
            f"{_pct(r.get('total_return'))} | "
            f"{_pct(r.get('cagr'))} | {_pct(r.get('vol_ann'))} | "
            f"{_num(r.get('sharpe'))} | {_num(r.get('sharpe_ex_bil'))} | "
            f"{_pct(r.get('max_dd'))} | {_pct(r.get('worst_month'))} | "
            f"{_pct(vs_ew)} | {_pct(vs_spy)} | {comparison} | {r.get('n_fills')} |")


HEADER = ("| Book | Evidence class | Span | Total | CAGR | Vol | Sharpe | Sharpe−BIL | Max DD | "
          "Worst mo | vs EW | vs SPY | Comparison | Fills |")
RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def _cohort_signature(r: dict) -> tuple:
    profile = r.get("execution_profile") or {}
    profile_signature = (
        json.dumps(profile, sort_keys=True, separators=(",", ":"))
        if isinstance(profile, dict)
        else profile
    )
    snapshot = r.get("data_snapshot") or {}
    snapshot_sha = snapshot.get("sha256") if isinstance(snapshot, dict) else snapshot
    return (r.get("source_sha256"), r.get("fill_model"),
            r.get("universe_policy"), r.get("initial_cash"), profile_signature,
            snapshot_sha)


def _select_report_cohort(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Select one assumptions cohort for the entire multi-window report.

    A grid refresh replaces artifacts independently. Selecting per window can
    splice old and new source/data/cost assumptions into one table. Keep the
    largest coherent cohort globally until its replacement overtakes it, and
    surface every omitted artifact as incompatible rather than as pending.
    """
    if not rows:
        return [], []
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault(_cohort_signature(row), []).append(row)
    selected = max(
        groups.items(),
        key=lambda item: (
            len(item[1]),
            max((r.get("generated_utc") or "") for r in item[1]),
            str(item[0]),
        ),
    )[1]
    selected_ids = {id(row) for row in selected}
    excluded = [row for row in rows if id(row) not in selected_ids]
    return selected, excluded


def _cohort_summary(rows: list[dict]) -> str:
    if not rows:
        return "none"
    row = rows[0]
    profile = row.get("execution_profile") or {}
    profile_id = profile.get("id") if isinstance(profile, dict) else profile
    snapshot = row.get("data_snapshot") or {}
    snapshot_sha = snapshot.get("sha256") if isinstance(snapshot, dict) else snapshot
    source = row.get("source_sha256")
    current_source, _ = runtime_source_hash()
    freshness = "current source" if source == current_source else "stale source"
    capital = (f"${float(row['initial_cash']):,.0f}"
               if row.get("initial_cash") is not None else "legacy_unstamped")
    return (f"source `{source or 'legacy_unstamped'}` ({freshness}); fill model "
            f"`{row.get('fill_model') or 'legacy_unstamped'}`; universe policy "
            f"`{row.get('universe_policy') or 'legacy_unstamped'}`; capital "
            f"`{capital}`; execution profile "
            f"`{profile_id or 'legacy_unstamped'}`; data snapshot "
            f"`{snapshot_sha or 'legacy_unstamped'}`")


def _write_reports(results_dir: Path, out_dir: Path) -> list[Path]:
    loaded = load_results(results_dir)
    results, incompatible = _select_report_cohort(loaded)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    written: list[Path] = []

    by_window: dict[str, list[dict]] = {}
    by_book: dict[str, list[dict]] = {}
    for r in results:
        by_window.setdefault(r["window"], []).append(r)
        by_book.setdefault(r["config_id"], []).append(r)

    # ---- master ---------------------------------------------------------- #
    grid_total = len(EXPECTED_GRID)
    lines = [
        "# Historical backtests of the league books — IN-SAMPLE-CONTEXT",
        "",
        f"_{len(results)} of {grid_total} planned (book, window) replays in the "
        f"selected cohort · generated {stamp}._",
        "",
        f"**Selected report-wide cohort:** {_cohort_summary(results)}.",
        "",
        (f"**Excluded as incompatible/stale:** {len(incompatible)} artifact(s). "
         "They are listed below and are not substituted into missing windows."
         if incompatible else
         "**Excluded as incompatible/stale:** none."),
        "",
        "Every book below is replayed by its OWN live strategy code through the "
        "real `sim/league.py` day-step: real orders, real t+1-open fills with the "
        "league's slippage and liquidity guards, real dividend crediting. Nothing "
        "is reimplemented for the backtest, and no bar is ever invented.",
        "",
        DISCLOSURES,
        "",
        "⚑ = window clamped to the earliest date the book's inputs exist "
        "(e.g. `dual_momentum` cannot start before BIL + 252 sessions).",
        "",
    ]
    for w in WINDOW_ORDER:
        rows = by_window.get(w)
        if not rows:
            continue
        bench = {r["config_id"]: r for r in rows if r["config_id"] in (EW, SPY)}
        rows = sorted(rows, key=lambda r: (r.get("total_return") is None,
                                           -(r.get("total_return") or 0)))
        lines += [f"## Window: {w}", "", HEADER, RULE]
        lines += [_row(r, bench) for r in rows]
        missing = [c for c in EXPECTED_GRID
                   if c[1] == w and c[0] not in {r["config_id"] for r in rows}]
        if missing:
            lines += ["", f"_pending: {', '.join(c[0] for c in missing)}_"]
        lines.append("")
    if not results:
        lines += ["_No replays have completed yet._", ""]
    if incompatible:
        lines += ["## Incompatible or stale artifacts excluded", ""]
        for row in sorted(incompatible, key=lambda r: (r["window"], r["config_id"])):
            lines.append(
                f"- `{row['config_id']}__{row['window']}` — cohort "
                f"`{_cohort_signature(row)}`"
            )
        lines.append("")

    md = out_dir / "README.md"
    resources.write_text_atomic(md, "\n".join(lines))
    written.append(md)

    # ---- per book -------------------------------------------------------- #
    for cid, rows in by_book.items():
        rows = sorted(rows, key=lambda r: WINDOW_ORDER.index(r["window"]))
        r0 = rows[0]
        bl = [
            f"# {r0['name']} (`{cid}`) — historical windows",
            "",
            f"_strategy `{r0['strategy']}` · cadence {r0['cadence']} · "
            f"generated {stamp}_",
            "",
            f"**Evidence and assumptions.** "
            f"`{r0.get('data_quality_class', 'legacy_unclassified')}`; starting "
            f"capital ${r0.get('initial_cash', 0):,.0f}; execution profile "
            f"`{(r0.get('execution_profile') or {}).get('id', 'legacy_unstamped')}`; "
            f"data snapshot "
            f"`{(r0.get('data_snapshot') or {}).get('sha256', 'legacy_unstamped')}`.",
            "",
            DISCLOSURES,
            "",
            HEADER, RULE,
        ]
        for r in rows:
            bench = {b: next((x for x in by_window.get(r["window"], [])
                              if x["config_id"] == b), None)
                     for b in (EW, SPY)}
            bench = {k: v for k, v in bench.items() if v}
            bl.append(_row(r, bench))
        bl += ["", "## Equity-curve detail", ""]
        for r in rows:
            me = r.get("monthly_equity") or []
            bl += [f"### {r['window']} — {r.get('start_date')} → {r.get('end_date')}",
                   "",
                   f"- sessions {r.get('n_sessions')} · fills {r.get('n_fills')} · "
                   f"rejected orders {r.get('n_rejected')} · dividend credits "
                   f"{r.get('n_dividend_credits')} (${r.get('dividend_cash', 0):,.0f})",
                   f"- equity ${r.get('equity_start', 0):,.0f} → "
                   f"${r.get('equity_end', 0):,.0f} · Sharpe-excess computed over "
                   f"{(r.get('bil_coverage') or 0) * 100:.0f}% of the window "
                   f"(BIL's first bar is 2007-05-30)",
                   f"- replay runtime {r.get('runtime_s')}s "
                   f"(screen {r.get('screen_s')}s, day-steps {r.get('step_s')}s) · "
                   f"screen rows {r.get('screen_rows')} · dividend rows in force "
                   f"{r.get('corporate_actions_dividend_rows')}",
                   ""]
            if me:
                bl += ["| Month | Equity |", "|---|---|"]
                bl += [f"| {m} | ${e:,.0f} |" for m, e in me[-24:]]
                if len(me) > 24:
                    bl.append(f"\n_… last 24 of {len(me)} months shown._")
                bl.append("")
        p = out_dir / f"{cid}.md"
        resources.write_text_atomic(p, "\n".join(bl))
        written.append(p)
    return written


def write_reports(results_dir: Path = RESULTS_DIR,
                  out_dir: Path = BACKTEST_DIR) -> list[Path]:
    """Rebuild one coherent report snapshot across parallel replay workers."""
    lock = REPO_ROOT / "scratch" / ".report-locks" / "backtest.lock"
    with resources.advisory_file_lock(lock):
        return _write_reports(Path(results_dir), Path(out_dir))


# The planned grid — kept here so the report can name what is still pending.
def _configured_grid(*, retained: bool) -> list[tuple[str, str]]:
    from engine.lib.data_quality import FIXED_ETF_STRATEGIES
    from farm.backtest.replay import WINDOW_MONTHS, excluded_reason
    from sim.strategies.configs import CONFIGS

    grid = []
    for c in CONFIGS:
        include = c.get("retain_latest_result", False) if retained else c.get("active", True)
        if not include:
            continue
        if excluded_reason(c["id"], c["strategy"]):
            continue
        for w in WINDOW_MONTHS:
            if w == "max" and c["strategy"] not in FIXED_ETF_STRATEGIES:
                continue
            grid.append((c["id"], w))
    return grid


EXPECTED_GRID = _configured_grid(retained=False)
RETAINED_RESULTS = _configured_grid(retained=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the backtest-farm reports.")
    ap.add_argument("--results", default=str(RESULTS_DIR))
    ap.add_argument("--out", default=str(BACKTEST_DIR))
    args = ap.parse_args()
    for p in write_reports(Path(args.results), Path(args.out)):
        log.info(f"[backtest-report] wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
