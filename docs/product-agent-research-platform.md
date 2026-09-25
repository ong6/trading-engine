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
and normalized bitemporal bars. P14 adds bounded nightly TradingView daily-history capture through
the existing single-writer queue. Its frozen current-liquid cohort, per-window checkpoints, raw
transcripts, failures, empty ranges, and coverage stay explicitly survivor-biased and retrieval-time
only; they do not replace licensed historical membership or point-in-time fundamentals/news.

Phase 3 status: accepted P8 buys freeze a deterministic exit contract at order creation. The
maximum hold is the selected 1-20 session horizon and the executable invalidation is a daily close
at or below the signal-day low; model-written invalidation prose never executes. Both conditions
create a pending sell for the following session rather than a same-bar fill. Entry and exit fills
receive append-only arrival/open/fill shortfall, simulated cost, session latency, and—where the
source timestamps exist—decision/tool/order latency. Missing sub-day fill timestamps are explicitly
represented by `session_open_date` precision.

Phase 4 status: a deterministic nightly report groups canonical traces by policy, cadence, prompt,
model, and version; scores each horizon separately; reports abstention, direction, confusion, Brier
calibration, return, excursion, latency, tokens, alerts, fills, exits, costs, shortfall, turnover, and
drawdown; and pairs policies only where date, ticker, horizon, and outcome prefix match uniquely. It
separates missing mature labels from still-immature labels. The existing 2022 named/blinded run is
included only as a contamination diagnostic; unrun probes and unavailable numeric forecasts remain
explicit, and all report output has no promotion authority.
The forward evaluation schedule is frozen from `2026-09-24T00:00:00Z`; expected hourly, four-hour,
and nightly windows are derived from registered DST-aware slots and missing windows are explicit.
The contamination suite now retains separate named/blinded, date-recall, prompt-order, and synthetic
trend-perturbation diagnostics. Date recall chose cash in all four windows, prompt reordering retained
the original XOM choices, and the synthetic perturbation fell to 25% accuracy and -11.02% compounded.
These are sensitivity diagnostics only; the post-cutoff prospective cohort is collecting.

Phase 5 status: [the provider-neutral manifest example](pit-import-manifest.example.json) defines the
only accepted CSV envelope for future licensed datasets. `python -m engine.pit_import MANIFEST
--data-root ROOT` audits by default; `--apply` is required to write isolated `pit_import_*` staging
tables. The importer validates an accepted license declaration, path containment, regular-file and
size/hash identity, exact columns, stable entity/security IDs, JSON payloads, duplicate keys, and
event/publication/availability ordering. It never writes operational `prices` or activates research.

SEC EDGAR forward capture is implemented for at most the latest five nightly candidates. It retains
the exact current-ticker-map and submissions responses, records the current mapping as
explicitly lacking historical-membership authority, and records material filing facts with report
date as event time, SEC `acceptanceDateTime` as publication time, and HTTP receipt as availability.
Activation is gated on a monitored contact identity in `TRADING_ENGINE_SEC_USER_AGENT` and a
successful one-ticker smoke test; this host's anonymous test received HTTP 403, so no failing timer
was installed. After setting it, run `python -m tools.sec_edgar_capture --tickers AAPL`; schedule
the command only after it returns `complete`. A partial or failed capture exits nonzero. SEC data
does not satisfy the paid historical-universe gate.

## Explicit external gates

- Sharadar/Norgate/news purchase: owner must approve initial and recurring spend and license terms.
- IBKR gateway, credentials, subscription, or API: requires a separately approved broker plan.
- Real capital: requires prospective evidence, immutable model revision, and explicit owner decision.
- TradingView automation: active under the owner's asserted non-display rights for internal realtime
  and historical research. Anonymous feed identity and freshness remain explicit and research-only.
- Official realtime cross-check: Alpaca Basic is supported as an IEX-only research source after the
  owner accepts its data terms and supplies API credentials. It is not consolidated or execution truth.

## Implemented product state — 2026-09-23

The locally buildable product is complete. Hourly and four-hour agents are shadow-only; the nightly
agent can request one typed trade, but deterministic code validates the symbol, confidence, size,
risk, next-open execution, and exits before the isolated US$10,000 simulator book changes. Every
accepted call is locked, idempotent, append-only, and joined from source evidence through decision,
tool attempt, order, fill, position, cash, equity, and delayed outcome. The hybrid policy remains a
buy-side veto and cannot rewrite an order or suppress a sell.

The forward dataset currently contains 11 retained traces and 42 decisions across active and legacy
policies. The active v3 intraday cohort begins with the first scheduled post-open window; all
currently possible 1/5/10/20-session labels remain immature because the
prospective schedule activates on 2026-09-24; no result has been fabricated or promoted. The
separate retrospective 2022 suite contains the original 8 named/blinded decisions and 12 diagnostic
probe decisions, all marked contamination-prone and non-promotable.

The algorithm fleet was revalidated as one 18/18 cohort against the same source, data snapshot,
execution profile, and 2026-09-22 anchor. The canonical validator reports `current`, with no missing,
invalid, duplicate, configuration-mismatched, or registration-mismatched result. This is historical
context only and does not change any strategy or authorize capital.

Operations are installed and self-tested: hourly, four-hour, and nightly timers are enabled and
active; their latest service results are successful; installed files match source; the simulator
self-test reports `pass` and `broker_route: absent`. The definitive recovery bundle is documented
in the completion audit. Calendar-mature outcomes and the external gates above are the only remaining
work; they are evidence collection or owner/vendor decisions, not missing implementation.

## Optional market-data sources

P13 adds a source admission registry and an official Alpaca Market Data adapter. A source is
classified separately for realtime research, historical staging, execution, operational-price
mutation, and redistribution. Responses are retained byte-for-byte before normalization, and every
observation exposes its feed, venue scope, event/receipt time, freshness class, entitlement class,
and receipt identity. Historical bars are explicitly retrieval-time observations written only to
the bitemporal fact ledger; they cannot become point-in-time backtest truth without the existing PIT
manifest audit. Missing credentials return `unavailable` without network or database access.
The revised intraday policies are versioned as v3, require a complete set of closed, no-more-than-
20-minute-old five-minute bars, and start after the open. Older v1/v2 artifacts remain immutable
legacy diagnostics and are excluded from active policy scoring.

The Mathieu2301 Tradingview-API project was reviewed at upstream commit
`5baea86c8c7e576f13464919c86c3b4c4b0ecf4c`. The runtime does not import that package; it implements
the bounded anonymous quote/chart framing contract directly and records that commit as its protocol
reference. TradingView is active under owner-asserted rights. Anonymous snapshots may resolve to a
different underlying feed than the requested listing venue—for example Cboe One/ICE for a Nasdaq
symbol—so requested symbol, resolved exchange, provider, age, spread availability, and consolidated
status are retained separately. Stale snapshots are stored but never admitted to agent prompts.
Historical daily bars are chunked within the protocol's 500-bar/550-day limits and scheduled in
small sequential slices. Successful or empty windows advance a symbol checkpoint; failed windows
remain visible and retry only to a fixed ceiling. Neither the archive nor its coverage projection
writes `prices`, prices fills, or expands execution authority.
