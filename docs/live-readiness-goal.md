# Goal: evidence-gated live readiness

Use this document as the handoff objective for the next Codex agent.

## Objective

Advance the trading engine from a reliable local paper-research system toward a
**live-capable but capital-disabled** system, while continuing disciplined research for a
strategy with credible net edge.

Treat these as parallel workstreams:

1. **Strategy evidence:** determine whether any frozen strategy has positive expected excess
   return after realistic costs, capacity limits, and drawdowns.
2. **Execution safety:** build and validate the broker-paper, reconciliation, risk, recovery,
   and audit machinery that would be required before real money could be considered.

Do not assume that an exploitable edge must exist. A valid outcome is that no tested strategy
qualifies. Engineering quality, positive standalone CAGR, or an attractive recent paper result
must not be substituted for evidence of positive excess return against a proper control.

## Current baseline

Re-query the live endpoints and rerun the quality gates before relying on these dated
2026-09-11 observations:

- The system is paper-only and has no broker integration or credentials.
- The nightly pipeline, API, UI, scheduler, paper league, and walk-forward validation are
  operational.
- All 21 active paper portfolios had current equity, and the then-current walk-forward cohort
  covered all 18 replayable books.
- The full Python suite with warnings as errors, Ruff, complexity checks, UI tests, and the
  production UI build pass.
- No strategy has established positive excess return over a prospectively frozen proper
  control.
- `sector_momentum` is the cleanest first candidate because it trades a fixed ETF universe,
  but its historical mean return trails SPY and its prospective record has only just begun.
- `xs_momentum_12_1` has an interesting but survivor-biased historical result; its frozen
  prospective candidate/control comparison has not reached its first signal.
- The E1 Monday experiment is an accumulating falsification test, not a deployable strategy.
- Point-in-time stock, fundamentals, and intraday datasets remain below their admission gates.
- The deployed working tree contains a large uncommitted/untracked implementation and
  `GET /meta.source_control` reports `local-only`; reproducibility and off-machine recovery are
  immediate risks.

Current authorities:

- `GET /meta`
- `GET /research/readiness`
- `docs/strategy-research-backlog.md`
- `data/reports/forward/`
- `data/reports/experiments/`
- `data/reports/walkforward/`

## Non-negotiable constraints

- Do not place real orders, add broker credentials, or create a usable LIVE toggle.
- Do not authorize capital, activate or retire a strategy, or change portfolio state
  automatically.
- Do not modify a frozen strategy, control, signal boundary, statistic, sample size, or kill
  rule after observing its forward results.
- Do not reset, backfill, silently repair, or replace an accumulating prospective record.
- Do not search nearby parameters after a failed result and present the winner as a new
  independent hypothesis.
- Do not use today's constituents or fundamentals as though they were point-in-time historical
  data.
- Do not interpret paper standings, raw CAGR, Sharpe, or a backtest PASS label as proof of edge.
- Preserve next-session execution, costs, capacity limits, data quarantine, corporate-action
  reconciliation, provenance, and immutable evidence checks.
- Fail closed on stale data, ambiguous order state, reconciliation differences, invalid
  provenance, or unavailable risk inputs.
- Keep model output advisory. A model may audit, summarize, or draft a charter; it may not be
  the source of a signal or an approval to trade.
- Work with the existing dirty tree. Never discard or overwrite unrelated changes. Do not
  commit or push unless the user explicitly asks.

## Workstream A: recoverable release

Make the currently deployed, tested state reproducible before increasing its operational scope.

Required outcomes:

- Inventory modified and untracked source, tests, service definitions, lockfiles, and generated
  evidence.
- Separate source/configuration from generated runtime artifacts without deleting evidence.
- Verify that a clean checkout plus documented restore inputs can install, test, build, and
  start the API and UI.
- Define encrypted backup and restore procedures for DuckDB, prospective checkpoints, broker
  journals when they exist, and deployment configuration.
- Add a release identity that binds source, dependency lockfiles, strategy registrations,
  schema version, and execution profile.
- Require one coherent release scan: retain private before/after filesystem identity for every
  Git-visible file and parent without embedding host-specific metadata in the manifest, and inspect
  the DuckDB schema through a no-follow descriptor whose leaf and parent-chain identities remain
  unchanged; bind the leaf by full metadata and each parent by device/inode so unrelated
  child-entry churn is tolerated without allowing path replacement.
  Recompute the protected runtime identity at the end so ignored executable source cannot appear
  only during one phase and become part of a mixed release identity.
  Re-read Git commit/tree/branch/status and required-file tracking state before success so a
  concurrent ref or index transition cannot be paired with an earlier worktree observation.
  Keep a private database parent-chain/leaf identity across the complete manifest build because the
  ignored runtime database is intentionally absent from the Git-visible tree hash.
- Arrange an off-machine upstream/backup only with the user's explicit approval and without
  publishing secrets or private runtime data.

Exit gate:

> The deployed paper system can be recreated on a second personal machine from reviewed source
> and documented backups, with all frozen evidence identities intact.

## Workstream B: strategy evidence

Continue existing prospective strategies unchanged:

- `sector_momentum` versus `spy_benchmark`;
- `xs_momentum_12_1` versus `ew_benchmark`;
- E1 SPY Monday through its exact 40-observation boundary.

Do not shorten their maturity gates. Historical research may improve context, but it cannot
turn these accumulating records into mature evidence.

For new research, prioritize data and mechanisms rather than more parameter sweeps:

1. Improve point-in-time data: delisted securities, historical membership, publication-dated
   fundamentals, and documented corporate actions.
2. Prefer fixed, liquid instrument universes while single-stock point-in-time coverage matures.
3. Test one economically motivated mechanism per charter.
4. Freeze the control, primary statistic, minimum effect, kill rule, execution profile, capital,
   capacity, data snapshot, and total trial count before running.
5. Use an exposure-matched static control where market exposure differs materially from SPY.
6. Stress doubled costs, one-session execution delay, missing fills, and plausible capacity.
7. Account for all attempted hypotheses and related variants when interpreting confidence.
8. Prefer stable net excess across regimes and modest perturbations over maximum backtest CAGR.

Potential research families, in priority order:

1. Fixed-ETF sector or asset-class relative momentum.
2. Slow trend or momentum with a separately justified crash-risk mechanism.
3. Cross-sectional momentum after point-in-time universe history is adequate.
4. Event drift only after reliable publication timestamps and event coverage exist.
5. Low-turnover quality/value plus momentum only after point-in-time fundamentals mature.
6. A portfolio of independently established modest effects, evaluated against an
   exposure-matched combination control.

Calendar variants, threshold tuning around rejected cells, and renamed versions of closed
hypotheses are low priority.

Strategy admission gate:

> A candidate must show positive net return and positive net excess over its frozen proper control,
> with the predeclared confidence interval excluding zero, acceptable drawdown and
> capacity, robustness to declared execution stresses, and a mature untouched prospective
> paper record. Passing permits human review only; it does not authorize live trading.

## Workstream C: capital-disabled broker shadow

Design a broker-neutral boundary without making real submission possible:

```text
BrokerAdapter
  get_account()
  get_positions()
  get_open_orders()
  submit_order()
  cancel_order()
  stream_fills()
```

Implement and prove in this order:

1. An adapter around the existing simulator.
2. Durable internal intent, order, execution, and reconciliation schemas with stable
   idempotency keys.
3. A broker paper-account adapter on personal infrastructure.
4. A disabled live adapter whose mutation methods fail closed.
5. A shadow runner that sends identical approved intents to the simulator and broker paper
   account.
6. Comparisons of acceptance, rejection, partial fills, timing, price, fees, slippage, cash,
   positions, cancellations, expirations, and corporate actions.

A timeout must leave an explicitly uncertain order requiring broker reconciliation. It must not
cause a blind retry or duplicate submission.

Exit gate:

> At least one uninterrupted month of broker-paper shadow operation has zero unexplained cash,
> position, order, or fill differences. Every explained difference is classified and retained.

## Workstream D: independent risk supervisor

All broker mutations must pass through a fail-closed risk service that is separate from strategy
logic and cannot be bypassed by the UI or scheduler.

At minimum enforce:

- allowlisted account, strategy, release, config hash, execution profile, and symbols;
- long-only cash equities/ETFs, regular session only;
- no margin, leverage, options, shorting, or extended-hours orders;
- maximum capital allocation, gross exposure, position concentration, order notional, daily
  turnover, order count, and percentage of recent dollar volume;
- fresh and non-quarantined prices, known market session, synchronized clock, healthy storage,
  and healthy broker connection;
- reconciled broker/local cash, positions, and open orders before submission;
- maximum daily loss and drawdown;
- tightly constrained order types and price collars;
- automatic halt on stale data, ambiguous submission, rejected reconciliation, unexpected
  corporate action, or breached risk limit.

Live authorization, if it is ever designed, must be a short-lived server-side lease bound to one
account, immutable release, strategy hash, and capital ceiling. Startup and restart state must always
be disabled.

Exit gate:

> Fault-injection tests prove that stale inputs, duplicate requests, timeouts, restarts,
> malformed broker responses, partial fills, and reconciliation mismatches cannot exceed the
> configured exposure or continue submitting orders.

## Workstream E: reconciliation, recovery, and operations

Build and drill:

- startup reconciliation before submissions are enabled;
- pre-order cash, position, buying-power, and open-order reconciliation;
- fill-by-fill and end-of-day reconciliation;
- immutable discrepancy and operator-decision records;
- cancel-all-and-disable and disable-without-cancel controls;
- a second kill path independent of the main UI;
- backup restoration and machine-loss recovery;
- broker disconnect, stale market data, partial fill, rejected cancel, and process-restart
  scenarios;
- bounded notifications for submissions, fills, rejections, discrepancies, stale data, risk
  halts, and authorization changes.

Real-money infrastructure belongs on a personal machine or personal VPS, not the current company
devbox. Use least-privilege credentials, encrypted storage and backups, private authenticated
access, off-machine audit retention, process supervision, and monitored UTC clock
synchronization. Browser requests may create intents but must never directly invoke a broker.

Exit gate:

> Repeated disaster drills recover to a reconciled, submission-disabled state without losing or
> duplicating an intent, order, fill, cash event, or operator decision.

## Capital progression

Do not implement later stages merely because earlier software exists.

| Stage | Capital | Gate |
|---|---:|---|
| Existing simulator | $0 | Current deterministic paper operation |
| Broker paper shadow | $0 | One clean reconciliation month |
| Live-data shadow | $0 | Real orders computed but submission technically disabled |
| Minimum canary | $500-$1,000 | Strategy and all operational gates passed; explicit human approval |
| Small live | At most 5% of intended allocation | Clean canary fills and measured slippage |
| Controlled expansion | At most 10-25% | At least three clean live months and no unexplained mismatch |
| Normal capped allocation | Risk-budget dependent | Six to twelve months of live operational evidence |

Capital increases depend on operational integrity, realized execution, and the frozen risk
budget, not recent profit. Any unexplained reconciliation difference returns the system to a
submission-disabled state.

## Definition of done

This overall goal is complete only when all of the following are true:

- A reviewed, recoverable release can be rebuilt on personal infrastructure.
- At least one frozen strategy clears its mature prospective strategy admission gate.
- Broker-paper shadow operation passes its uninterrupted reconciliation period.
- Independent pre-trade risk controls and all kill paths pass fault-injection tests.
- Backup, restart, disconnect, partial-fill, and disaster-recovery drills pass.
- Security and operations documentation is current.
- A human performs a separate go-live review and explicitly authorizes one immutable release,
  one strategy, one broker account, and one minimum capital ceiling.

Until then, the engine remains paper-only. Do not weaken a gate to manufacture completion.

## Continuation assignment

Do not repeat the initial Workstream A audit. The dated recoverability and worktree reviews now
exist; `tools.worktree_audit`, `tools.release_manifest`, `tools.backup_database`, and
`tools.install_automation` are implemented and exercised locally. They establish inventory,
identity, local backup, and unattended-deployment mechanisms, but they do not make the current
working tree a release. A same-host isolated-directory schema-v2 restore now proves that the
database, prospective checkpoints, and bounded monitoring artifacts can serve the read-only API
together; it is not an independent-machine or off-machine recovery proof. The remaining Workstream
A blockers are reviewable commits, a user-authorized upstream or other encrypted off-machine
destination, and a successful restore drill on an independent personal machine.

For each continuation:

1. Re-query `GET /meta` and `GET /research/readiness`, inspect the exact Git/release state, and
   rerun checks proportionate to any files changed. Treat generated forward reports as the
   authority for advancing evidence.
2. Preserve the frozen 111-file research-runtime identity after any explicitly documented
   correctness migration and while prospective evidence accrues. If the live source and published
   walk-forward cohort differ, report `stale-source` and let the scheduled revalidation restore a
   matching cohort; do not reconstruct evidence or reformat/refactor the boundary as style-only
   work.
3. Let scheduled producers add genuinely new observations. Do not rerun closed grids, tune a
   frozen candidate, reconstruct a missing historical receipt, or count repeated history as new
   evidence.
4. Continue narrow cleanup only where a concrete ownership, correctness, operability, or
   documentation defect is demonstrated and behavior can be verified.
5. Do not add broker integration on this host. External source-control, backup, broker-paper, or
   independent-machine work requires the appropriate user-selected destination or credentials.
6. Report verified changes, tests, live invariants, remaining blockers, and the next smallest
   gated step without claiming profitability before a strategy clears its admission gate.
