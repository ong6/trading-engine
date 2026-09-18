# Documentation map

Use this page to distinguish current operating truth from dated evidence. A date in a
document filename or top-level title marks a snapshot: preserve it for provenance, but do
not assume its counts, process state, or recommendations supersede the current guides. The
undated strategy backlog is the current decision ledger; dates inside it label the historical
measurements supporting those decisions, not the live runtime state.

## Operating contract (read first if you are an agent)

- [`../AGENTS.md`](../AGENTS.md) — the contract: maintain mode, admission test, budgets,
  session shape, BUILDLOG v2 format. Overrides everything below except the feedback ledger.
- [`feedback.md`](feedback.md) — the owner's dated verdicts and the rule each one changed.
  Newest entry wins.
- [`scope.md`](scope.md) — in scope now, approved plans, frozen "not yet" areas with their
  unfreeze triggers, and the "proposed, not approved" parking list.
- [`scope-budget.json`](scope-budget.json) — LOC ceilings per frozen layer and the BUILDLOG
  entry budget, enforced by `tests/test_operating_contract.py`.
- [`metrics.md`](metrics.md) — what the drift snapshot measures and how to read it; the
  generated table is [`../data/reports/metrics/README.md`](../data/reports/metrics/README.md).
- [`plans/README.md`](plans/README.md) — follow-up plans:
  [P1 appliance mode](plans/p1-appliance-mode.md), [P2 league collapse](plans/p2-league-collapse.md),
  [P3 point-in-time data](plans/p3-point-in-time-data.md), [P4 broker decision](plans/p4-broker-decision.md).

## Current operating documents

- [`how-it-works.md`](how-it-works.md) — architecture, schedules, paper league, UI/API,
  and operations.
- [`live-readiness-goal.md`](live-readiness-goal.md) — the former handoff objective for strategy
  evidence, point-in-time data upgrades, optional algorithm/agent/hybrid paper flows, and
  capital-disabled execution hardening; it does not authorize live trading. Since 2026-09-18 it
  is reference only: its workstreams C, D and E are frozen pending
  [P4](plans/p4-broker-decision.md), and `scope.md` is the work queue.
- [`recoverability-audit-2026-09-11.md`](recoverability-audit-2026-09-11.md) — dated
  Workstream A inventory and closure sequence; its observed counts are not live status.
- [`worktree-review-2026-09-11.md`](worktree-review-2026-09-11.md) — recursive ownership
  inventory and review-safe commit sequence for the large local implementation.
- [`settlement-runbook.md`](settlement-runbook.md) — manual adjudication of dead or
  untradeable positions.
- [`../BUILDLOG.md`](../BUILDLOG.md) — chronological implementation decisions and
  incidents.

## Design and specification

- [`design/trading-engine-design.md`](design/trading-engine-design.md) — governing engine
  design; §12 wins on conflicts.
- [`design/trading-execution-design.md`](design/trading-execution-design.md) — execution
  process and exit criteria.
- [`design/paper-authority-state-machine.md`](design/paper-authority-state-machine.md) —
  capital-disabled design for future short-lived paper authority, atomic consumption,
  revocation, and fail-closed recovery; no writer or runtime authority exists.

## Current strategy and evidence status

- [`review-2026-09-06.md`](review-2026-09-06.md) — dated full-review snapshot, extended with
  the then-current 2026-09-07 v4 walk-forward cohort.
- [`strategy-research-backlog.md`](strategy-research-backlog.md) — what has been ruled
  out, what remains uncertain, and the
  [ordered next admissible actions](strategy-research-backlog.md#next-admissible-actions).
- `GET /meta` and the dashboard prospective-evidence cards — live authority for scheduler,
  source, nightly/miner, walk-forward-cohort, and frozen forward-monitor state. In particular,
  `miner_evidence` reconciles the four canonical producers, while `friday_postflight` interprets
  the auxiliary receipt against its Saturday schedule and grace window. Read the projected state,
  not `logs/friday-postflight.json` alone: a well-formed old receipt can still be stale. Generated
  forward reports remain the authority for each monitor's full evidence detail;
  dated narrative documents are snapshots.
- `GET /research/readiness` and the dashboard readiness cards — live, read-only admission
  gates for stock-selection, fundamentals, and intraday research. They require both elapsed
  time and per-date breadth and never imply profitability or activate a strategy.
- The dated “Live decision checkpoint” in
  [`strategy-research-backlog.md`](strategy-research-backlog.md) records the latest reconciled
  counts and the next permitted action. The endpoints and generated reports supersede that
  checkpoint as soon as a scheduled producer publishes newer evidence.
- [`../data/reports/walkforward/GUIDE.md`](../data/reports/walkforward/GUIDE.md) — the evidence map
  for the latest generated historical walk-forward cohort in the sibling `README.md`. The
  completed 2026-09-13 Sunday revalidation stamped all 18 active, replayable books with source
  `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`, data snapshot
  `039bd02c7cdb5678f28e5cf93098393c7e695625c4fc37fc5281d2e8e19fa80e`, and one coherent
  source/data/execution cohort, signature
  `b304ae92d54e27a8f3a3adaa77dcf5b77175f9be141e71dfa232f29c3b32aec2`, with the versioned
  comparator declaration and 2026-09-11 anchor.
  On 2026-09-13 the protected source first advanced after the weekly liquidity pending-backfill
  retry, Nasdaq plural security-class parser correction, and atomic universe reconciliation/CSV
  publication, then advanced to
  `cfcdcb5dc3bb690567173dd87d85adff49e32b76863f4a8e0494f923dcf34592` when the historical
  replay scratch-cardinality guard and corporate-actions proof checks were made explicit under
  optimized Python and the replay, proof, walk-forward, and shakedown scratch connections were
  made exception-safe, followed by exception-safe ownership for the historical screen,
  execution-drag reader, queue grids, queue schema setup, and legacy dividend backfill. Those
  final daily screen/league ownership, atomic-publication, committed-run artifact recovery,
  screen recovery-anchor/connection corrections, and exception-safe temporary DataFrame cleanup
  advanced the protected identity to
  `8ed2b751127c17ab3631583ae4f0e9e87b8b041250263b447092c5c5c8711d90`. Centralized
  interruption-safe transaction cleanup then advanced the current protected identity to
  `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75` and was explicitly
  migrated through XS contract v20, sector contract v9, and E1 contract v6 without changing their
  observations, strategy rules, or execution economics. The final identity also includes
  failure-safe cleanup of the signal breadth reader's temporary universe relation and the
  historical screener's call-scoped temporary tables. The
  published 18-result cohort is therefore source-matching and current.
  Older unstamped artifacts remain absolute historical context only.
  Publication time is not the same as live freshness: the `walkforward_evidence` object in
  `GET /meta` is the authority on whether that cohort still matches every active config and the
  deployed source.
- [`execution-capital-data-hardening-2026-09-06.md`](execution-capital-data-hardening-2026-09-06.md#measured-five-year-capital-and-cost-sensitivity--2026-09-07)
  — capital and doubled-cost sensitivity summary; machine-readable cells are under
  `data/reports/capital-sensitivity/`.
- [`../data/reports/league.md`](../data/reports/league.md) — latest completed nightly paper
  standings snapshot for active portfolios. Its companion `league.csv` is the complete historical
  equity export, including retired books; current between-run stale exposure comes from `/meta`,
  and none of these is proof of an edge.
- [`../data/reports/forward/sector_momentum.md`](../data/reports/forward/sector_momentum.md)
  — maturity-aware nightly check of the selected strategy's frozen 12-month kill rule,
  with an exact baseline-state and append-only execution-ledger checkpoint.
- [`../data/reports/forward/xs_momentum_12_1.md`](../data/reports/forward/xs_momentum_12_1.md)
  — prospective 12-1 momentum comparison, frozen before its first signal. The generated
  report is authoritative for its current boundary and status.
- [`../data/reports/experiments/e1-spy-monday-forward.md`](../data/reports/experiments/e1-spy-monday-forward.md)
  — the shorter-horizon frozen SPY Monday experiment. Its generated report is authoritative
  for the current count; the immutable-prefix checkpoint is the sibling JSON file. After
  exactly 40 eligible observations, the predeclared `KILL`/`SURVIVE` gate runs once.

The current conclusion is deliberately conservative: no strategy has established positive
excess return over a prospectively frozen proper control. The engine remains paper-only.

## Strategy research charters

All hypotheses, expectations, controls, and kill criteria are under [`charters/`](charters/):

- [`charters/fixed_etf_rebalancing_premium.md`](charters/fixed_etf_rebalancing_premium.md)
  records the completed quarterly equal-weight ETF candidate versus the identical
  unrebalanced basket. Its confidence gate failed, so v1 is closed; neither rule is
  registered as a paper book.
- [`charters/ew_dd_throttle.md`](charters/ew_dd_throttle.md) and
  [`charters/ew_sector_capped.md`](charters/ew_sector_capped.md) are completed,
  rejected candidate studies; neither became a league book.
- [`charters/ew_gross_voltarget.md`](charters/ew_gross_voltarget.md) is closed as
  `INCONCLUSIVE-LEGACY`. Its matched-static review found no established timing edge,
  and its old artifacts lack complete provenance.
- [`charters/vix_term_spy_timing.md`](charters/vix_term_spy_timing.md) records the
  completed VIX/VIX3M SPY/BIL timing experiment. Its timing excess was significantly
  negative against a static exposure-matched control, so v1 is rejected and closed.
- [`charters/turn_of_month_spy.md`](charters/turn_of_month_spy.md) records the completed
  four-session turn-of-month SPY/BIL experiment. Its timing excess and confidence
  interval were negative against the exposure-matched static control under baseline
  and doubled costs, so v1 is rejected and closed.
- [`charters/sell_in_may_spy.md`](charters/sell_in_may_spy.md) records the completed
  November-April SPY/BIL experiment. It trailed the exposure-matched static control,
  its confidence interval crossed zero, and its worst drawdown was materially worse,
  so v1 is rejected and closed.
- [`charters/xs_momentum_12_1.md`](charters/xs_momentum_12_1.md) records the original
  historical-control charter and its dated prospective-forward addendum. The book is
  active but the fair forward comparison is waiting for its first frozen signal.
- [`charters/multi_asset_trend.md`](charters/multi_asset_trend.md) was tested and retired
  after validation.
- [`charters/xs_reversal_1m.md`](charters/xs_reversal_1m.md) was withdrawn before
  registration after its diversification premise failed the initial check.

## Historical audits and snapshots

These remain valuable evidence about what was known on their dates. Their old strategy
counts, fold counts, and recommendations are not current configuration:

- [`architecture-review-2026-09-02.md`](architecture-review-2026-09-02.md)
- [`evaluation-2026-09-02.md`](evaluation-2026-09-02.md)
- [`data-sources-audit-2026-08-20.md`](data-sources-audit-2026-08-20.md)
- [`evidence-ceiling-2026-08-20.md`](evidence-ceiling-2026-08-20.md)
- [`fill-model-audit-2026-08-20.md`](fill-model-audit-2026-08-20.md)
- [`leveraged-etf-audit-2026-08-20.md`](leveraged-etf-audit-2026-08-20.md)
- [`split-restatements-reaudit-2026-09-03.md`](split-restatements-reaudit-2026-09-03.md)
- [`synthesis-price-adjustment-and-fills-2026-08-20.md`](synthesis-price-adjustment-and-fills-2026-08-20.md)
- [`execution-capital-data-hardening-2026-09-06.md`](execution-capital-data-hardening-2026-09-06.md)
  — implementation and measured-sensitivity snapshot for fill-model v4, capital, capacity,
  provenance, and quarantine behavior.

## Generated reports

Generated artifacts live under [`../data/reports/`](../data/reports/). Start with the
[`generated-evidence map`](../data/reports/README.md), which classifies every top-level report and
identifies the live authority for its status. Read each applicable family guide—and each
experiment directory's own guide—before individual rankings: they record the cohort, benchmark,
evidence limitations, trial count, and statistical interpretation. The
  [`../data/reports/experiments/README.md`](../data/reports/experiments/README.md) separates the
accumulating E1 record from closed historical studies, while
[`../data/reports/capital-sensitivity/README.md`](../data/reports/capital-sensitivity/README.md)
explains why sampled capacity and cost tolerance are not evidence of profitability. The
[`../data/reports/sweeps/README.md`](../data/reports/sweeps/README.md) marks the unversioned sweep
directories as historical archives and points back to the current decision ledger.

## Source and lint policy

Ruff covers active Python and tests. `archive/` is excluded because it is immutable retired
source retained for historical reproducibility; changing it solely to satisfy current
style rules would alter the snapshot. Archived code is not imported by active runtime
paths. The UI, generated scratch trees, and `.venv` remain outside Python lint scope. CI audits
the locked Python runtime and installed UI production dependencies; Dependabot proposes weekly
`uv`, GitHub Actions, and npm updates as reviewable pull requests and never merges or deploys them
automatically.
