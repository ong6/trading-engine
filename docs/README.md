# Documentation map

Use this page to distinguish current operating truth from dated evidence. A date in a
document filename or top-level title marks a snapshot: preserve it for provenance, but do
not assume its counts, process state, or recommendations supersede the current guides. The
undated strategy backlog is the current decision ledger; dates inside it label the historical
measurements supporting those decisions, not the live runtime state.

## Operating contract (read first if you are an agent)

- [`../AGENTS.md`](../AGENTS.md) — the contract: maintain mode, admission test, budgets,
  session shape, BUILDLOG v2 format. Overrides everything below except the feedback ledger.
- [`direction.md`](direction.md) — north star (autonomous, AI-in-the-loop, net-profitable),
  what "makes money" means, stages to live capital, and the order admitted work matters in.
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
  [P3 point-in-time data](plans/p3-point-in-time-data.md), [P4 broker decision](plans/p4-broker-decision.md),
  [P5 agent paper decisions](plans/p5-agent-paper-decisions.md),
  [P6 alpha experiment](plans/p6-alpha-experiment.md), and
  [P7 autonomous paper trial](plans/p7-autonomous-paper-trial.md),
  [P8 daily opportunity agent](plans/p8-daily-opportunity-agent.md), and
  [P9 multi-cadence agent tools](plans/p9-multi-cadence-agent-tools.md), and
  [P10 contamination-aware 2022 agent replay](plans/p10-2022-agent-replay.md), and
  [P11 forward agent evaluation](plans/p11-forward-agent-evaluation.md), and
  [P12 agent research product](plans/p12-agent-research-product.md).

## Current operating documents

- [`product-agent-research-platform.md`](product-agent-research-platform.md) — canonical product
  requirements for point-in-time data, agent decisions, execution, evaluation, and external gates.
- [`how-it-works.md`](how-it-works.md) — architecture, schedules, paper league, agent services,
  UI/API, and operations.
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

- [`strategy-research-backlog.md`](strategy-research-backlog.md) — what has been ruled
  out, what remains uncertain, and the
  [ordered next admissible actions](strategy-research-backlog.md#next-admissible-actions).
- [`charters/credit_confirmed_equity_trend.md`](charters/credit_confirmed_equity_trend.md) —
  the frozen P6 registration for one credit-confirmed SPY/BIL alpha experiment.
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
  for the latest generated walk-forward cohort (18 active, replayable books). Cohort, source, and
  data identities live in the generated artifacts, not in prose; the `walkforward_evidence` object
  in `GET /meta` is the authority on whether that cohort still matches every active config and the
  deployed source.
- [`execution-capital-data-hardening-2026-09-06.md`](history/execution-capital-data-hardening-2026-09-06.md#measured-five-year-capital-and-cost-sensitivity--2026-09-07)
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

Dated snapshots live in [`history/`](history/README.md), whose index says what each one is and
why it is kept. They remain valuable evidence about what was known on their dates; their old
strategy counts, fold counts, process state, and recommendations are not current configuration.
[`history/live-readiness-goal.md`](history/live-readiness-goal.md) is the former handoff objective
and does not authorize work or live trading; `scope.md` is the queue.

- 2026-08-20: [`data-sources-audit`](history/data-sources-audit-2026-08-20.md),
  [`evidence-ceiling`](history/evidence-ceiling-2026-08-20.md),
  [`fill-model-audit`](history/fill-model-audit-2026-08-20.md),
  [`leveraged-etf-audit`](history/leveraged-etf-audit-2026-08-20.md),
  [`synthesis-price-adjustment-and-fills`](history/synthesis-price-adjustment-and-fills-2026-08-20.md)
- 2026-09-02 to 09-06: [`architecture-review`](history/architecture-review-2026-09-02.md),
  [`evaluation`](history/evaluation-2026-09-02.md),
  [`split-restatements-reaudit`](history/split-restatements-reaudit-2026-09-03.md),
  [`review-2026-09-06.md`](history/review-2026-09-06.md),
  [`execution-capital-data-hardening-2026-09-06.md`](history/execution-capital-data-hardening-2026-09-06.md)
- 2026-09-11: [`recoverability-audit-2026-09-11.md`](history/recoverability-audit-2026-09-11.md),
  [`worktree-review-2026-09-11.md`](history/worktree-review-2026-09-11.md)
- 2026-09-22 to 09-23: [`agent-trading-review`](history/agent-trading-review-2026-09-22.md),
  [`agent-backtesting-roadmap`](history/agent-backtesting-roadmap-2026-09-23.md),
  [`agent-research-product-completion-audit`](history/agent-research-product-completion-audit-2026-09-23.md)

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
