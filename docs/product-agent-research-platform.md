# Product Requirements: Agent Research and Paper-Trading Platform

## Product outcome

Build an always-on, capital-disabled research product that can compare deterministic algorithms,
LLM-only policies, and algorithm-plus-LLM policies without look-ahead, evidence pooling, or hidden
execution assumptions. Every future decision must be reproducible from its information set and
joinable to later outcomes, simulated execution, cost, and risk evidence.

## Users

- Research owner: selects budgets, cohorts, controls, and promotion gates.
- Operator: monitors freshness, failures, exposure, and recovery without editing evidence.
- Research agent: proposes bounded hypotheses and decisions using admitted facts only.
- Auditor/reviewer: reconstructs any decision and verifies data, model, execution, and outcome.

## Product principles

1. Event time is not availability time. Every fact is bitemporal and revision-preserving.
2. A model proposes semantics; deterministic code owns capital, risk, size, and execution.
3. One decision window produces one immutable trace and at most one terminal outcome.
4. Labels arrive only after their horizon and are unavailable to the policy.
5. Compared policies receive the same admitted facts, timing, costs, and capital.
6. Historical LLM results are contamination diagnostics; prospective evidence controls promotion.
7. Missing data, failed calls, missed windows, and rejected trades are outcomes, not rows to erase.

## Functional requirements

### Data plane

- Canonical fact envelope: entity/security IDs, event/published/available/ingested timestamps, source,
  adapter version, immutable revision, raw receipt hash, and normalized value hash.
- Exact raw receipts for EOD, intraday quote/bar, news, filing, fundamental, and corporate-action data.
- Point-in-time joins use availability cutoff, with tests rejecting report-period or latest-row joins.
- Security master supports symbol changes, listings, delistings, share classes, mergers, and IDs.
- Vendor-neutral manifests specify schemas, licenses, checksums, coverage, revision semantics, and
  migration isolation.

### Decision plane

- Versioned policies for hourly shadow, four-hour shadow, nightly agent, deterministic control, and
  hybrid veto.
- Exact input/output retention, model/prompt/tool identity, latency, tokens, evidence references, and
  terminal status.
- Multi-day watches with immutable alert lifecycle and fresh trigger-time reassessment.
- Strict abstain/no-action behavior for missing, stale, malformed, or identity-drifted evidence.

### Execution plane

- One typed simulator trade tool; no model-authored quantity, account, or risk limits.
- Deterministic concentration, exposure, cash, liquidity, earnings, and quarantine gates.
- Next-session-open swing fills; no same-bar fills.
- Deterministic maximum holding period and machine-readable invalidation/stop exits.
- Decision-to-tool, tool-to-order, order-to-fill latency and implementation shortfall.
- Quote/trade replay with partial fills, queue position, and cancel latency before intraday authority.

### Evaluation plane

- Canonical trace per window and append-only decision, execution-link, and delayed-label records.
- Frozen 1/5/10/20-session labels: return, SPY/control excess, adverse/favorable excursion, and cost.
- Paired evaluation by policy/cadence/prompt/model with coverage and missing-window accounting.
- Metrics: abstention, accuracy, confusion matrix, Brier/calibration, forecast error, return, drawdown,
  excursion, turnover, costs, shortfall, latency, tokens, alert precision, rejection/fill/exit rates.
- LLM contamination suite: named/blinded, recall probe, synthetic perturbation, prompt permutations,
  post-cutoff cohort, and deterministic control.

### Operations

- Bounded read-only status for data freshness, trace completeness, label maturity, execution linkage,
  scheduler state, drift, and recovery evidence.
- Backup and restore rehearsal after schema changes and after first order/fill/exit lifecycle.
- Frozen evaluation cohorts cannot be tuned mid-run.

## Non-functional requirements

- One DuckDB writer; atomic source publication and transaction cleanup.
- Append-only evidence except explicitly modeled current state.
- No credentials, broker connectivity, or real capital on this host without later approved plans.
- Full replay from retained evidence makes zero model or network calls.
- Source budgets, bounded public projections, and safe identifiers remain enforced.

## Success gates

| Gate | Minimum | Consequence |
|---|---:|---|
| Operational pilot | 90 days and 60 sessions | Assess reliability, not superiority |
| Trade expectancy | 20 completed round trips | Permit an estimate with uncertainty |
| Prompt/cadence comparison | Same paired windows and facts | Permit comparison after frozen sample |
| P7 policy comparison | 12 paired monthly windows | Permit comparative verdict |
| Real-capital discussion | Post-cutoff evidence plus immutable model revision | Permit a new plan only |
| Historical stock research | Audited PIT data/license | Permit new historical charters |

## Delivery phases

1. P11 canonical forward traces and delayed labels.
2. Bitemporal fact envelope and raw intraday provenance.
3. Deterministic exits, latency, shortfall, and full execution attribution.
4. Paired reports, calibration, contamination tests, and completeness alerts.
5. Vendor-neutral PIT adapters plus SEC EDGAR forward ingestion.
6. Paid historical data acquisition after owner spend and license approval.
7. Broker-paper evaluation only under a separate execution plan.

Phase 2 status: the generic receipt/fact envelope and exact-response capture for hourly/four-hour
agent-visible quotes are implemented. Each admitted quote links to the same retained provider bytes
and normalized bitemporal bars. Broad nightly archive capture remains a separate scale-up item; its
legacy DataFrame fetch is not presented as exact-response evidence.

## Explicit external gates

- Sharadar/Norgate/news purchase: owner must approve initial and recurring spend and license terms.
- IBKR gateway, credentials, subscription, or API: requires a separately approved broker plan.
- Real capital: requires prospective evidence, immutable model revision, and explicit owner decision.
