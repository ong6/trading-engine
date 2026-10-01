---
plan: P18
title: Shared backtest core
status: done
opened: 2026-10-01
owner_decision: approved by the owner 2026-10-01
---

## Goal

Provide one public, deterministic backtest core under `farm/study/` for event and portfolio
studies. A study supplies a declarative strategy and pure decision function; the core supplies
point-in-time data views, universe membership, fills and costs, benchmarks, statistics, sealed
development/holdout windows, run identity, reports, process-pool execution, and synthetic
known-answer proofs. A study should no longer need its own evaluator.

## Why now

Separate evaluators have disagreed on benchmark costs, the time base for deflated Sharpe, and
parallel execution. Those disagreements can reverse a research verdict. P18 standardises the
measurement path before more studies use it, while P16 W11 remains the broader synthetic world
for the agent pipeline. P18's synthetic market is price-only and reusable by that later work.

## Design invariants

- The core is generic public infrastructure. Strategy registrations, parameter searches, study
  censuses, findings, and result artifacts remain with the consuming study.
- A decision sees only values whose availability timestamp is at or before its declared decision
  time and whose session is no later than the view's hard maximum date. Violations raise
  `LookAheadError`; rows are never silently dropped to make a run pass.
- A fill must occur after the information used to decide it. `next_open` is always a later
  session. A declared intraday or auction fill may occur in the same session only when its fill
  point follows the decision point; `at_open` use of the official open requires the explicit
  `open_as_indication` approximation and is disclosed.
- Strategy excess is net strategy return minus gross benchmark return over the identical window.
  Benchmark costs are allowed only in the separately labelled `allocation` comparison mode.
- Calendar-series statistics include every eligible session, with zero return on inactive days.
  The DSR wrapper accepts the trial-census N as a required argument and has no default.
- Runs are immutable by identity, deterministic across worker counts, and have no timers,
  services, live-store writes, broker path, order authority, or promotion authority.

## Existing-module map

| Existing module | Decision | P18 use |
|---|---|---|
| `farm/stats/inference.py` | reuse | Call its Sharpe/DSR moments and percentile-bootstrap primitives; P18 requires census N and passes the calendar-session return series rather than active-trade returns. |
| `farm/stats/equity.py` | reuse | Use the single max-drawdown and worst-month definitions. |
| `farm/walkforward/protocol.py` | wrap | Keep its immutable fold shape and calendar-boundary helpers; P18 owns explicit yearly development folds plus a separately sealed holdout. |
| `farm/walkforward/monthly.py` | reuse | Use the existing Politis–Romano stationary-bootstrap index implementation with a registered seed and block length. |
| `sim/execution.py` | wrap | Build P18's exact, hashed study-cost registry over the existing named-profile concepts. Do not alter existing profiles or simulator defaults. |
| `sim/fills.py` | reuse contract, leave code alone | Preserve fractional shares, trailing-MDV capacity, adverse-side pricing, and never-invent-a-bar behaviour. Its DuckDB/next-open implementation remains the live league path; P18 adds study-only fill points without changing it. |
| `sim/calendar.py`, `sim/nyse.py` | reuse | Use stored sessions where present and the published NYSE rules for session stepping. No price value is learned from the calendar. |
| `farm/backtest/*` | reuse patterns, leave code alone | Retain scratch isolation, frozen provenance, atomic output, real-code-path replay, and independent arithmetic proofs. The league-specific replay/report APIs are not duplicated or modified. |
| `farm/p16_statistics.py` | leave alone | Its factor-neutral, fixed-horizon DSR contract remains P16-specific. P18 uses the lower-level inference functions so its required input is a complete calendar-session series and an explicit census N. |
| `engine.lib.provenance`, `engine.lib.resources` | reuse | Use canonical hashing and atomic file writes for identities, markers, JSON, Markdown, and census rows. |

## Scope

All implementation is confined to `farm/study/**` and `tests/test_study_*.py`; this plan and the
standard are the only new documentation files.

1. **Strategy specification (`spec.py`).** Add frozen value objects for `FillPoint`, `ExitRule`,
   `Order`, `EventStrategy`, and `PortfolioStrategy`. Support long and short orders, the four
   declared entry points, the three exit-rule families, explicit USD notional, rebalance
   schedules, and validated decision times. Strategy callbacks are importable pure functions;
   mutable closures and non-canonical parameters are rejected before a run identity is made.
2. **Point-in-time data (`data.py`).** Add an immutable data declaration and view over normalized
   bars and optional auction/intraday/funding data. Column-level availability gates expose opens
   at open, later fields only at their timestamp or declared source lag, and enforce a hard maximum
   date in every query. Accept an optional independent secondary price source with the same bar
   schema and its own declaration; secondary gaps stay gaps and are never filled from the primary.
   Provide frame construction for tests/synthetic data and a read-only DuckDB adapter for an
   explicitly supplied store copy.
3. **Universe and survivorship (`universe.py`).** Resolve listing intervals and point-in-time
   trailing liquidity. Handle delist exits at the last available close, otherwise apply the
   configured delisting return (default −30%) and count it. A current-listings-only or missing
   delisted-name source is structurally marked `SURVIVOR-BIASED SOURCE`.
4. **Costs (`costs.py`).** Register the four profiles exactly as approved, with a canonical
   payload SHA-256 and `verified_against_fills=False`: `ibkr_tiered_auction_v1`,
   `ibkr_fixed_v1`, `binance_spot_base_v1`, and `binance_perp_base_v1`. Shares are fractional,
   costs apply per side, sell-only SEC/TAF terms stay separate, crypto liquidity tiers are exact,
   and perp funding is a supplied data series. Also register the simulator's existing
   `baseline_v1` by delegating to `sim.execution.cost_components` and retaining its existing
   canonical hash. Every run validates one primary and at least one distinct harsher sensitivity.
5. **Benchmark (`benchmark.py`).** Implement gross equal-weight-eligible-universe, single-ticker,
   and zero-return cash comparators on the exact study window. Compute the primary excess as
   strategy net minus benchmark gross and always retain the absolute-net-positive check. Permit a
   cost-bearing comparator only under explicit `mode="allocation"`, labelled in all artifacts.
6. **Statistics (`stats.py`).** Produce trade mean, entry-session-clustered standard error and
   one-sided t; complete calendar-session returns; annualised Sharpe and calendar-series DSR with
   required census N; yearly post-burn-in folds and last-three-fold recency; stationary-bootstrap
   CI; max drawdown, worst month, exposure, turnover; and order notional as a fraction of MDV60
   and supplied auction volume. Event-strategy capital is maximum concurrent slots times slot
   notional.
7. **Protocol and census (`protocol.py`, `census.py`).** Add `Windows(dev_folds, holdout)` and
   validate at least six development folds. Development views cannot load holdout rows. Opening a
   holdout atomically creates the caller-supplied one-shot marker before access and refuses an
   existing marker. Hash exact strategy source, canonical parameters, core version, all selected
   cost hashes, and the data snapshot into one run identity recorded in reports and trial rows.
   Document and emit the study-owned CSV schema without creating a repository census.
8. **Runner (`run.py`).** Execute variant × fold jobs in a process pool, defaulting to
   `min(16, os.cpu_count())`; force BLAS-related thread counts to one before worker imports. Sort
   jobs and results canonically, derive all random streams from explicit seeds, and serialize
   floats/keys consistently so serial and parallel outputs are byte-identical.
9. **Report (`report.py`).** Atomically write Markdown and JSON with fixed sections for data,
   costs, benchmark, independent-price cross-check, variants, folds, optional holdout, generated
   caveats, and one plain-English line per variant. The cross-check reports trade-day coverage;
   signed `primary / secondary - 1` mean, median, p5, p95, and share beyond 0.5% for every fill
   field used; the per-trade result recomputed entirely on covered secondary prices; and uncovered
   trade count. It never fills secondary gaps from primary data. Generate caveats for
   open-as-indication, survivor bias, every unverified cost profile, and fewer than 100 trades.
   Include run identity, runtime, worker count, delisting fallback count, and absolute-net/excess
   checks.
10. **Synthetic proving ground (`synthetic.py`).** Generate a seeded price-only market with
    liquidity tiers, fat-tailed daily/overnight returns, delistings including zeros, a known
    tier-specific gap-down fade, cross-sectional momentum, and pure noise. Keep normal-suite
    fixtures small. Prove at least 45/50 one-sided `t >= 2` detections and a pooled edge estimate
    within two standard errors of truth; prove null size at alpha 0.05 over 200 seeds lies inside
    the exact 99% binomial band; and prove the look-ahead, survivorship, cost, and benchmark
    canaries. A synthetic secondary source has a planted biased open and proves the cross-check's
    sign, distribution, recomputed trade result, and uncovered count. Any optional larger run is
    marked `slow`.
11. **Worked example (`examples/`).** Add a generic textbook SPY 200-session trend rule against
    gross SPY buy-and-hold. Exercise it end to end on synthetic data in the normal suite. Its CLI
    requires an explicit read-only database path (a `tools.backup_database create` copy for real
    data), an output directory outside tracked `data/`, a primary cost and a harsher sensitivity.
    It refuses the live default store path.

## Not in scope

- Editing P15-hashed files, P7/P8/P16 paths, the live simulator, existing cost-profile behaviour,
  service units, schedules, schemas, endpoints, dashboards, or operator CLIs.
- Reading or writing the live DuckDB store, retaining a real-data copy, fabricating missing bars,
  or committing generated results under `data/`.
- Any private strategy, prompt, parameter set, registration, census contents, finding, or result.
- Broker connectivity, credentials, real capital, automatic promotion, tuning after a holdout is
  opened, or treating a historical result as prospective evidence.
- P16 W11's text/filing/agent synthetic world. P18 exposes reusable seeded price data only and
  does not modify P16.

## Done when

Checkpoint `p18-plan` is complete when this approved plan, its index row, the P18 budget key and
owner-feedback entry, and `docs/backtest-standard.md` are committed and pushed on
`p18/backtest-core` after the operating-contract tests and full suite pass.

Checkpoint `p18-core` is complete when items 1–7 and focused `tests/test_study_*.py` tests pass,
including exact hand calculations for every fee term, point-in-time/holdout failures, fold and
calendar-day statistics, benchmark cost asymmetry, delisting handling, hashes, census schema, and
secondary-source isolation with a planted biased open. Then the full suite and whole-repository
Ruff pass and the branch is pushed.

Final completion requires items 8–11 and all of:

```sh
.venv/bin/python -m pytest -q -W error tests/test_study_*.py
.venv/bin/python -m pytest -q -W error -n auto
.venv/bin/ruff check .
.venv/bin/python -m tools.metrics_snapshot --check-budget
```

The focused results must report power ≥ 90% over 50 registered seeds, the planted estimate within
2 SE, null alpha-0.05 rejections inside the exact 99% binomial band over 200 seeds, all four
canaries passing, and byte-identical serial/parallel JSON. The example must produce the same fixed
report sections and identity without writing tracked output. `git diff origin/main --` over the
P15 registration manifest's file list must be empty.

## Budget

- Up to 9 logical commits including this planning checkpoint, each below 1,500 inserted non-data
  lines.
- Up to 3,000 new lines under `farm/study/`, 2,500 under `tests/test_study_*.py`, and 800 across
  the two P18 documentation files. These are a P18 review budget recorded under its own key in
  `docs/scope-budget.json`, not restored repository-wide layer ceilings.
- Three sessions/checkpoints: plan; core items 1–7; runner/report/synthetic/example items 8–11.
  No dependency, data purchase, service, endpoint, migration, or live-state budget is granted.

## How to run this plan

One writer works only in `~/engine-lanes/p18` on `p18/backtest-core`. Do not use reviewer
sub-agents, self-review rounds, sleep loops, the live checkout, or another lane's claimed files.
At the start of each checkpoint, rebase on `origin/main`, confirm the claims and clean tree, inspect
`GET /meta`, and run a dry-run metrics snapshot. Stop rather than touching a failed producer or
shared file outside P18's entry.

1. Commit and push the survey, approved plan, standard, ledger entries, budget key, snapshot, and
   BUILDLOG entry. Write `checkpoint p18-plan` STATUS and stop.
2. After the orchestrator says `go`, implement only items 1–7 in small commits. Run focused tests,
   then the full suite once, Ruff, and the budgeted snapshot; push, write `checkpoint p18-core`,
   and stop.
3. After the next `go`, implement only items 8–11, run the registered proving ground and final
   gates once, push, write `done` STATUS with the measured power/size/canary/identity results, and
   stop.

## Risks

| Risk | Detection / rollback |
|---|---|
| Timestamp semantics leak a close, holdout, or future membership | Column-level availability and hard-max tests fail closed; remove the P18 change without touching stored evidence. |
| Exact fee formulas drift behind a convenient generic abstraction | Hand-computed buy/sell and tier-boundary tests bind every term and profile hash. |
| Sparse strategies get attractive DSR from active-day sampling | Calendar-session fixture includes all zeros and asserts its DSR input length and value. |
| A benchmark accidentally pays the strategy's costs | Identity canary requires excess exactly equal to negative strategy cost; allocation mode is a distinct labelled path. |
| Parallel workers change ordering, random streams, or floats | Canonical jobs, per-job seeds, single-thread BLAS, and byte comparison against one worker. |
| A secondary source silently becomes a fallback or hides trade-day gaps | Keep sources independently declared and keyed; report coverage and uncovered trades, and recompute only the covered secondary subset. |
| Synthetic thresholds are brittle or tuned after observation | Generator parameters and seed ranges land before results; failures are reported, not tuned inside the same checkpoint. |
| Store-backed example touches live state | Explicit path, read-only connection, live-default-path refusal, and copy-only runbook; tests use temporary synthetic stores. |

Rollback is deletion of `farm/study/` and its P18 tests/docs before any consumer adopts it. No
existing schema, runtime path, evidence, service, or registration is migrated by this plan.
