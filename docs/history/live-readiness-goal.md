# Goal: evidence-gated data, decision, and execution readiness

> **Historical reference, not the work queue** (moved to `docs/history/` on 2026-09-24). This
> document drove the build loop through 2026-09-17 and produced the agent, broker-paper and
> risk-supervisor layers now frozen in [`scope.md`](../scope.md). Its "Continuation assignment" is
> superseded by [`AGENTS.md`](../../AGENTS.md). The owner decided
> [P4](../plans/p4-broker-decision.md) on 2026-09-20 (IBKR eventually, on personal hardware, under
> a separate execution-layer plan); workstreams C, D and E still admit no work until such a plan is
> approved. Apart from relative links, nothing below has been edited; read it for the gates a future execution plan would
> inherit, and [`direction.md`](../direction.md) for where the project is going now.

Use this document as the handoff objective for the next Codex agent.

## Objective

Advance the trading engine from a reliable local paper-research system toward a
**live-capable but capital-disabled** system, while improving point-in-time data and testing
deterministic algorithms, constrained agents, and combinations of both for credible net edge.

Treat these as parallel workstreams:

1. **Data readiness:** improve provenance, point-in-time correctness, independent verification,
   and useful coverage without treating row count as information quality.
2. **Strategy evidence:** determine whether any frozen algorithm-only, agent-only, or hybrid
   policy has positive expected excess return after realistic costs, capacity limits, and
   drawdowns.
3. **Paper-agent safety:** allow a constrained agent to create automatically executable paper
   proposals only after schema, evaluation, risk, attribution, and operational gates pass.
4. **Execution safety:** build and validate the broker-paper, reconciliation, risk, recovery,
   and audit machinery that would be required before real money could be considered.

The target is a multi-mode decision system, not an agent replacement for the trading engine:

| Mode | Decision source | Required behavior |
|---|---|---|
| **Algorithm-only** | Frozen deterministic strategy | Runs unchanged when every model service is unavailable. |
| **Agent-only experimental** | Constrained model proposal | Uses a separately registered paper book and fails to no action. |
| **Hybrid** | Frozen algorithm candidates plus a frozen model role | Keeps algorithm and model contributions separately attributable and follows a predeclared model-failure policy. |

All three modes may share admitted market data, deterministic risk checks, simulation, accounting,
and operational infrastructure. They must not share decision authority, silently change mode, or
pool evidence. Every portfolio registration must declare exactly one mode, and hybrid
registrations must declare whether the model ranks, vetoes, or makes a bounded sizing adjustment.
Data improvements must remain usable by deterministic strategies without introducing a model
dependency or changing a frozen algorithm's decision rule.

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
- Do not authorize capital or activate or retire an established strategy automatically.
  Automatic state changes are permitted only inside explicitly registered experimental paper
  books after their paper-agent authority gate passes.
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
- Preserve deterministic algorithm flows as first-class production paths. An agent must never be
  required for an algorithm-only book to run.
- A model may be a source of a proposal only for a separately registered agent-only or hybrid
  paper book. It cannot approve itself, bypass deterministic validation, mutate evidence, or
  place a broker order.
- Do not expose a generic shell, SQL interface, filesystem, arbitrary network client, or broker
  tool to the model. Treat retrieved text as untrusted data and constrain every model boundary
  with a versioned structured schema.
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

Every agent experiment must preserve attribution through frozen comparison books:

1. **Algorithm-only:** the existing deterministic strategy and execution path, with no model
   dependency.
2. **Agent-only experimental:** the agent proposes from an allowlisted, point-in-time context;
   this mode remains paper-only and cannot inherit evidence from an algorithm book.
3. **Hybrid:** the same deterministic candidates feed a frozen agent role such as rank, veto, or
   bounded sizing adjustment.
4. **Control:** the proper static or exposure-matched comparator required by the charter.

Run these as distinct portfolios with separate configuration hashes, order/fill ledgers, costs,
and prospective evidence. Do not merge their results or let one mode silently fall back to
another. Model failure means no action for an agent-only book; a hybrid charter must predeclare
whether model failure means no action or the unmodified algorithm signal.

Strategy admission gate:

> A candidate must show positive net return and positive net excess over its frozen proper control,
> with the predeclared confidence interval excluding zero, acceptable drawdown and
> capacity, robustness to declared execution stresses, and a mature untouched prospective
> paper record. Passing permits human review only; it does not authorize live trading.

## Workstream C: constrained automatic paper agent

Add the agent as an optional decision layer around the existing deterministic engine, not as a
replacement for strategy calculation, risk, execution, or accounting:

```text
validated point-in-time snapshot
  -> algorithm candidates and/or bounded agent context
  -> versioned structured TradeProposal
  -> deterministic recomputation and risk validation
  -> idempotent paper intent
  -> existing next-open simulator
  -> positions, accounting, attribution, and immutable audit
```

Required outcomes:

- Define an immutable data contract with observation time, availability time, ingestion time,
  source/version, revision, raw-record hash, adjustment policy, and quarantine state.
- Admit new data only after provenance, point-in-time, coverage, freshness, reconciliation, and
  incremental-value checks. More data alone is not an exit criterion.
- Build a bounded context service; the model cannot query arbitrary storage or choose its own
  tools, URLs, symbols, strategies, parameters, or execution rules.
- Define a strict `TradeProposal` carrying proposal/idempotency IDs, model/prompt/tool versions,
  release/config/data-snapshot hashes, strategy and mode, signal time, expiration, instrument,
  side, maximum notional, invalidation, confidence, rationale, and evidence references.
- Independently recompute eligibility, prices, features, sizing, liquidity, exposure, and risk.
  Model-provided numbers are claims, not authorities.
- Record inputs, structured outputs, validation results, approvals, rejections, no-actions,
  orders, and fills in an append-only decision ledger.
- Evaluate malformed output, hallucinated facts, stale/quarantined data, replay attempts, prompt
  injection, unavailable tools, model changes, timeouts, restarts, and adversarial portfolio
  states.
- Run the agent under process supervision after terminal disconnection, with bounded retries,
  one lock-protected decision per window, health reporting, and a persistent paper kill switch.
- Use the existing systemd-supervised Trae CLI proxy on loopback as the sole model transport for
  this project. The connector is pinned to `http://127.0.0.1:8317/v1/responses` and the allowlisted
  `GPT-5.6-Sol:max` catalog entry; do not add a direct-provider or alternate-model fallback. The
  connector must expose no proxy credentials, offer no model tools, and fail closed when the proxy
  or allowlisted model is unavailable. Schedule model generation only after the shadow runner's
  prompt, output validation, idempotency window, and audit behavior are frozen and tested, and keep
  it behind a persistent default-disabled shadow kill switch.

Authority stages:

| Stage | Agent authority | Portfolio effect |
|---|---|---|
| Observe | Read bounded snapshots and explain | None |
| Shadow | Produce and score proposals | Separate counterfactual ledger only |
| Approved paper | Submit validated proposals after human approval | Existing simulator only |
| Automatic paper | Submit validated proposals under a preconfigured lease and risk budget | Registered paper books only |

Automatic-paper authority gate:

> At least 60 completed market sessions across shadow and approved-paper operation have zero
> policy bypasses, duplicate intents, unexplained accounting differences, or missing decision
> traces; fault-injection and restart drills pass; model/config/data identities and limits are
> frozen; and a human explicitly enables a bounded automatic-paper lease. This gate authorizes
> simulated execution only and is not evidence of profitability.

## Workstream D: capital-disabled broker shadow

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

1. **Completed locally 2026-09-13:** an internal adapter around the existing simulator.
   `server/broker_contract.py` defines typed account, position, order, fill, submit, cancel, and
   cursor contracts; `server/simulator_broker_adapter.py` projects the existing portfolio and
   simulator ledgers without adding a fill path. Submission maps a caller-owned opaque idempotency
   key to the simulator's numeric order ID: exact replay returns the original order and reuse for
   different terms fails closed. Cancellation is account-scoped and idempotent only after
   confirmed cancellation. Fill observation is bounded and rejects mismatched, orphaned, or
   duplicate ledger state. The boundary has no route, schedule, agent wiring, network client,
   credential handling, external broker, or live toggle. Its source identity is a separate
   release-manifest group, and the frozen 111-file algorithm runtime is unchanged.
2. **Completed locally 2026-09-13:** durable internal intent, submission-event, order-observation,
   execution, and reconciliation ledgers with stable idempotency keys. Canonical payloads and
   hashes make exact replay verifiable and conflicting key reuse fail closed. Submission commits
   an append-only `submission_started` event before invoking an adapter and appends
   `submission_acknowledged` only after validating the exact returned order. A timeout, exception,
   process exit, or malformed acknowledgement therefore leaves an explicit `uncertain` state;
   every later submission attempt stops before invoking the adapter. Only separately retained
   reconciliation evidence may resolve that state—there is no blind retry. These tables and the
   two-phase coordinator remain internal and unwired to HTTP, agents, schedules, or current
   portfolio flows.
   **Extended locally 2026-09-13:** `server/broker_submission_resolution.py` can adjudicate one
   uncertain attempt from a twice-identical complete adapter snapshot while a durable halt is in
   force. It retains and hash-binds the full snapshot and halt-control identity, verifies exact
   request terms, broker-order identity, fill totals, timing, and replay, and classifies the
   attempt as open, filled, terminally partial-filled, or `not_observed_burned`. It never submits,
   cancels, or permits retry; even stable absence permanently burns the original idempotency key.
   Startup separates resolved attempts from unresolved ambiguity but remains halted, and a
   resolved open order remains a blocker.
3. A broker paper-account adapter on personal infrastructure.
4. **Completed locally 2026-09-13:** a structurally disabled live adapter. It has no
   configuration, SDK, endpoint, credential access, or network imports; authoritative live reads
   report unavailable and submit/cancel reject unconditionally. No runtime toggle can enable it.
5. A shadow runner that sends identical approved intents to the simulator and broker paper
   account.
6. Comparisons of acceptance, rejection, partial fills, timing, price, fees, slippage, cash,
   positions, cancellations, expirations, and corporate actions.
   **Started locally 2026-09-13:** a read-only reconciliation layer captures complete bounded
   account, position, open-order, and fill snapshots through the neutral interface. It retains
   exact venue-native snapshots separately from normalized economic comparisons, correlates
   orders and fills by stable intent key, classifies cash, buying-power, position, order, fill,
   price, cost, and availability differences, and records unavailable venues as a non-match.
   Each snapshot requires two identical complete bounded reads, and cross-venue comparison repeats
   the expected snapshot after reading the observed venue so changing state fails closed. Exact
   snapshot and normalized result publication is atomic and exact-key replay is immutable. This is
   local machinery only: without a paper-broker adapter it provides no broker claim and no
   operational shadow run.

A timeout must leave an explicitly uncertain order requiring broker reconciliation. It must not
cause a blind retry or duplicate submission.

Exit gate:

> At least one uninterrupted month of broker-paper shadow operation has zero unexplained cash,
> position, order, or fill differences. Every explained difference is classified and retained.

## Workstream E: independent risk supervisor

All broker mutations must pass through a fail-closed risk service that is separate from strategy
logic and cannot be bypassed by the UI or scheduler.

**Started locally 2026-09-13:** `server/broker_risk.py` defines a pure, deterministic pre-trade
contract over a caller-supplied immutable snapshot. Twenty ordered gates bind account, policy,
strategy, release, config, execution profile, symbol, order type/time-in-force/session, dependency
health, reconciliation, operational-halt and corporate-action state, current price,
reference-price deviation, cash, capital, gross and symbol exposure, turnover, order count,
liquidity participation, daily loss, drawdown, and close-only sell inventory. Exposure, cash,
turnover, order-count, and sell-inventory calculations include reservations for pending order
remainders so individually valid concurrent intents cannot ignore already committed capacity.
Decisions retain and hash the exact normalized policy, identity, intent, and snapshot
and must fully recompute during verification. Snapshot observation and quote timestamps must be
UTC and agree with their declared market dates; future, cross-date, and older-than-policy quotes
fail the market/session gates. Reconciliation evidence has its own policy-bounded maximum age.
Every decision has a hash-bound short TTL. The internal two-phase
submission coordinator requires a verified exact-intent pass decision before the expiry instant;
a failed or expired decision is retained and stops before creating a submission event or calling
an adapter. An already acknowledged exact replay remains readable after expiry without another
adapter call, while an uncertain submission retains reconciliation priority and cannot be retried.
An expired never-submitted decision cannot be silently replaced under the same intent key: a fresh
evaluation requires a new intent identity. This is still not imported by any API, agent, strategy,
or scheduler entry point and grants no current execution authority.

`server/broker_risk_snapshot.py` assembles those inputs from a twice-stable broker-adapter snapshot,
an exact retained reconciliation bound to that snapshot, typed current-price/performance evidence,
and `server/broker_risk_control.py`. Positions are valued with complete current marks rather than
average cost; pending and partially filled order remainders become reservations. Missing or extra
marks, terminal orders reported as open, changed state, stale reconciliation, and hash mismatch
fail closed. The separate control is append-only and one-way: missing state is halted, recorded
halts are hash chained and survive restart, and no enable, clear, lease, authorization, API, or
schedule exists. A local operator CLI can independently inspect or append a halt without the main
UI; it cannot clear one. Consequently every currently assembled snapshot is deliberately halted.

`server/broker_startup_readiness.py` adds a read-only startup assessment. It revalidates exact
current adapter state around the evidence reads, requires current matching reconciliation, rejects
any uncertain submission or cancellation and any incomplete emergency-stop operation, verifies
the durable control, and can report only `reconciled_halted` or `blocked`, always with
`submission_authority = none`.

`server/broker_risk_fault_drills.py` now defines a bounded, source-hash-bound thirty-four-case local
drill over stale input, reconciliation failure, operational halt, unresolved corporate action,
pending-order reservations, loss/drawdown limits, timeout/re-entry, malformed acknowledgement,
conflicting replay, expiry, restart-persistent default halt, assembled-snapshot halt enforcement,
partial-fill/expiration representation, rejected cancellation, reconciliation differences, and
changing snapshots. It also proves halt-first cancel-all success and replay, durable uncertainty
without blind retry after a cancellation timeout, and fail-closed paper-lease candidate
assessment and lease-to-intent eligibility. Startup recovery additionally proves that unresolved
cancellation and emergency-stop state blocks readiness. The suite also proves that stable venue
absence never makes an uncertain submission retryable and that retained adjudication survives
restart and fails closed after tampering. It additionally proves agent-only and hybrid intent
bindings are derived from complete retained evidence and reject covered-row tampering. The exact
current suite also covers the pure activation planner's rejection of changed startup/control
evidence and carries `execution_authority = none`; it neither persists an authority decision nor
enables a route.
`server/broker_paper_lease.py` now defines the non-issuing half of a future paper-authority design.
Its closed, maximum-five-minute candidate contract binds the human approval evidence, one
decision window, mode, agent policy and registration, simulator account, strategy, data snapshot,
model/prompt/toolset identities, execution profile, risk policy, release manifest, readiness
assessment, symbol set, capital, order notional, and order count. Pure admission requires an exact
externally trusted lease hash, current immutable bindings, a reviewed release, the automatic-paper
readiness gate, and a fresh reconciled-but-halted startup assessment. Even a fully passing
candidate reports only `admissible_for_future_activation`, `activation_implemented = false`, and
`submission_authority = none`. There is no issuer, trust-store loader, persistence, activation,
consumption, renewal, revocation, API, schedule, or submission integration. Those state-machine
pieces require separate review before any mutation path may be wired.

`server/broker_paper_intent.py` now adds a pure, non-consuming check for one proposed future lease
use. It re-verifies the complete broker-risk decision and binds its exact order request, policy,
account, strategy, release, config, execution profile, symbols, pass status, and expiry to the
lease. Agent facts not present in broker risk—mode, policy registration, data snapshot, retained
context and decision-window identities—arrive through an explicit hash-bound input whose identity
must be externally trusted. Agent-only evidence additionally binds the accepted proposal,
validation, exact request, side, symbol, notional ceiling, signal date, and expiry. Hybrid
evidence instead binds the deterministic candidate, terminal veto outcome, effective-order-set
identity, and proof that the exact request remained in that set. A second externally trusted hash
binds current consumed order count and notional; the check enforces the next order against both
per-order and cumulative lease limits. A pass reports only
`eligible_for_future_consumption`, with `activation_implemented = false`,
`consumption_implemented = false`, and `submission_authority = none`. The module has no database,
reservation, activation, consumption, adapter, API, or submission path. Eligibility is not safe
to act on until a separately reviewed durable state machine can atomically revalidate and consume
capacity exactly once.

`server/broker_human_paper_review.py` now provides the source-neutral, non-authorizing precursor
to that missing trust layer. It loads complete retained agent-only or hybrid evidence for one
exact simulator request and emits a maximum-five-minute packet binding the policy, decision
window, context, data snapshot, request, and accepted proposal or surviving hybrid order. A
registered hybrid model-failure fallback is explicit; vetoed buys, expired proposals, request
drift, and generation before retained hybrid evidence fail closed. The packet's checksum detects
ordinary corruption but is not authentication. It intentionally contains no selected approval
source or signer policy, no approval verifier or approval, no lease, activation, route, API,
schedule, persistence, or submission authority. A separate read-only verifier reconstructs every
packet field from the retained database evidence and exact request, rejects rehashed forgeries or
changed source evidence, and enforces the packet's generation and expiry instants. That stronger
check still does not authenticate a human or grant authority. Packet schema v2 adds only bounded
review content: independently validated price, notional, limit, and deterministic order-impact
facts plus model thesis, invalidation, or hybrid reason explicitly classified as untrusted model
rationale. Registered fallback is classified separately, and raw context, prompts, model
requests, and evidence-ID arrays remain excluded.

`tools.review_agent_paper_intent` now provides the operator boundary for that packet. Build mode
accepts one exact simulator request and prints JSON only to stdout; verify mode accepts one
maximum-1-MiB strict-JSON object on stdin and reconstructs it against retained evidence and the
current UTC time. Both force DuckDB read-only and reject duplicate keys, non-finite or oversized
input, expiry, changed evidence, and packet drift. The CLI has no approval/rejection command,
signer, packet writer, persistence, activation, lease, adapter, route, or submission capability.

The next source-neutral contract now exists in `server/broker_human_paper_approval.py`. It defines
an exact decision envelope and an explicitly supplied signer-policy shape, including approval
source, signer identity, signer-policy ID/version, detached authenticator algorithm/bytes, exact
packet and request hashes, one-use approval ID, decision, and bounded timestamps. Policy scope is
closed over signer identities, modes, registered policies, and reserved simulator accounts. A pure
verifier accepts only an explicitly supplied policy identity and detached-authenticator callback;
even successful authentication reports design evidence only, with no trust loader, selected
policy, approval grant, route, or submission authority. A separate
read-only composition reconstructs the exact packet from retained DuckDB evidence before invoking
authentication; a rehashed packet forgery therefore cannot reach the authenticator callback. This
does not make the supplied policy trusted. Closed object and bounded strict-JSON parsers now reject
wrong schema versions, missing/unknown/duplicate fields, noncanonical timestamps and authenticator
encoding, malformed scope lists, and oversized input. They do not choose or trust a source. No
default policy, key, trust store, algorithm implementation, CLI, API, or writer was added.
Selecting the real approval source/signing mechanism and independently loading its policy remains
an operator decision.

`server/broker_human_paper_approval_store.py` now adds a separate durable,
non-authorizing replay-protection ledger for successful retained-evidence authentication results.
It retains the exact policy, envelope, review packet, and verification payload; globally sequences
and hash-chains observations; and makes approval ID, envelope, packet, and request identities
unique. Exact retained replay is idempotent, including after the short decision window expires,
without repeating authentication. Conflicting reuse, malformed retained payloads, source-evidence
drift, and chain tampering fail closed. Approve and reject observations are both recordable, but
every row still reports `human_order_approval_granted = false`, no production authority
consumption, an absent paper route, and `submission_authority = none`. It has no API, CLI,
scheduler, trust loader, selected policy, adapter, or broker path and has not been initialized in
the live store.

The future durable state machine is now specified in
`docs/design/paper-authority-state-machine.md`, and
`server/broker_paper_authority_transcript.py` provides a pure verifier for its proposed
hash-chained activation, consumption, and revocation transcript. The design preserves the
one-way halt ledger: activation anchors an epoch to the latest halt event rather than clearing it;
any later halt, process restart, lease expiry, or terminal revocation closes that epoch.
Consumption counters are recomputed from unique immutable intent events, and each future
consumption must be committed atomically with the broker ledger's uncertain pre-adapter
`submission_started` marker. This closes the design-level crash gap where capacity and submission
state could otherwise diverge. The verifier has no DuckDB, event writer, adapter, route, or
schedule and always reports `submission_authority = none`. Transcript schema v2 binds the
authority-aware risk evaluation rather than an ordinary broker-risk decision. Durable
uncertain-submission adjudication now exists separately and remains unwired. A production writer
remains blocked on the remaining trust and recovery gates. The read-only
loaders in `server/agent_paper_evidence.py` now derive agent-only `PaperIntentBindings` and hybrid
`HybridPaperIntentBindings` from complete retained shadow paths instead of accepting
caller-selected fields or hashes. They recompute decision-window identities, verify frozen policy
and Trae identities, retained context and request/response evidence, and bind the future simulator
request to an accepted proposal or surviving hybrid effective order. They have no write, lease,
activation, consumption, adapter, route, or scheduling surface. A separate read-only usage loader
requires the complete trusted transcript head, re-verifies the full chain, rejects truncated or
closed epochs, and derives counters and prior consumed identities without caller-supplied usage.
A pure atomic consumption planner re-verifies the candidate, retained intent, complete usage,
exact request, and authority-aware risk evaluation, then computes one canonical bundle containing
the expected future broker intent, uncertain `submission_started` commitment, and next authority
event. It has no persistence, transaction, adapter, route, or submission surface. A read-only
runtime/control
loader derives a process-local non-persisted random epoch and twice-stable latest verified halt
anchor; restart, missing state, tampering, or a concurrent halt cannot preserve the same binding.
Only the human trust loader remains absent because no approval source, signing mechanism, or signer
policy is selected; the source-neutral envelope contract is not a trust loader.

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

## Workstream F: reconciliation, recovery, and operations

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
host. Use least-privilege credentials, encrypted storage and backups, private authenticated
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
| Agent shadow | $0 | Structured proposals retained; no portfolio mutation |
| Human-approved agent paper | $0 | Agent evaluation and deterministic validation gates pass |
| Automatic agent paper | $0 | Sixty-session authority gate and bounded lease pass |
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
- Algorithm-only operation remains independent of model availability, and algorithm-only,
  agent-only, and hybrid books have isolated configuration, attribution, and evidence.
- Every agent-visible datum is point-in-time, versioned, and reproducible; every proposal is
  structured, idempotent, independently validated, and permanently auditable.
- The automatic-paper authority gate passes without creating any broker or live-capital path.
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
5. Preserve algorithm-only books while introducing agent work through separate agent-only and
   hybrid paper registrations. Never reuse the retired agentic implementation or its evidence as
   proof that the replacement passed its gates.
6. Do not add broker integration on this host. External source-control, backup, broker-paper, or
   independent-machine work requires the appropriate user-selected destination or credentials.
7. Report verified changes, tests, live invariants, remaining blockers, and the next smallest
   gated step without claiming profitability before a strategy clears its admission gate.

Near-term implementation order:

1. **Completed 2026-09-13:** establish the shadow proposal ledger and bounded operator read model
   without granting execution authority. The ledger retains the exact validated context payload
   for replay, while `GET /agent/proposals` exposes only a bounded, closed operational projection.
2. Upgrade shared data contracts, provenance, point-in-time coverage, quality gates, and snapshot
   identity so algorithm-only, agent-only, and hybrid books consume the same admitted facts.
   **Started 2026-09-13:** context schema v10 publishes honest daily-price and cash-dividend fact
   envelopes and
   bounded registered-universe total-return features with exact start/end price facts, dividend
   facts, corporate-action coverage, session counts, and recomputable hashes. It retains explicit
   missing-provenance limitations and binds the allowlisted Trae connector identity. A separate
   append-only `agent_daily_price_observations` ledger now captures every normalized price row in
   the registered strategy lookback before a signal-date model call, retaining observation hashes,
   revision chains, adapter/library identity, and unchanged-versus-revised classifications without
   changing the operational `prices` table or the frozen algorithm runtime. Existing rows enter as
   explicitly labelled baseline snapshots, so they are not misrepresented as historical source
   observations. `GET /agent/data/daily-prices` exposes bounded coverage and revision counts, and
   a separate persistent data-capture timer records this evidence even while model generation is
   disabled. A separate append-only `agent_corporate_action_observations` ledger now captures
   normalized dividend and split rows in the registered lookback with the same baseline,
   unchanged, and value-revision semantics. Selected dividend facts bind their exact immutable
   observation and conservative capture-time availability. `GET /agent/data/corporate-actions`
   exposes bounded coverage and revision counts. Neither ledger modifies the operational cache or
   deterministic algorithm flow. A third append-only ledger now retains exact bounded Yahoo
   chart-v8 response bodies fetched after normalized capture, with request/response hashes,
   timestamps, byte counts, endpoint-version identity, and yfinance version. Each new response now
   also creates append-only normalized source observations derived directly from those exact bytes.
   A matching selected fact can bind that source observation and truthfully report retained raw
   response identity without changing the operational cache. Separate hash-bound links to the
   earlier cache-derived observations remain explicitly later corroborations: they do not rewrite
   baseline observations or claim that the original ingestion payload was retained.
   `GET /agent/data/provider-responses` exposes bounded receipt, source-observation, total-link,
   distinct-observation, and overlapping action-set addition/removal counts without exposing
   response bodies. Repeated identical responses remain separate receipt-time evidence and cannot
   inflate either source-revision or distinct-corroborated-observation counts.
   The status now also verifies the retained ledgers and compares only each newest exact source
   revision with the corresponding current cache row using identical canonical fact shapes. Its
   aggregate-only alignment report separates matching values, value drift, and absent cache rows
   without exposing market values or mutating the cache. Readiness surfaces these counts and keeps
   point-in-time data blocked when source/cache alignment is unavailable, incomplete, or drifting.
   A separate read-only operator CLI now lists bounded discrepancy identities and hashes and can
   build or revalidate a one-hour packet for one exact discrepancy. The packet binds field-level
   cache/source values, the newest source revision, and all retained confirmations of that value,
   but carries no recommendation or decision. Its future disposition vocabulary is guarded
   repair, retain with justification, quarantine, or defer; none is implemented as a mutation.
   Rehashed forgery, changed cache state, changed source evidence, malformed input, and expiry fail
   closed. This advances diagnosis without treating provider disagreement as proof that the cache
   is wrong.
   Original raw responses for historical baseline observations, source publication time, a stable
   provider dataset/version identity, complete deletion/tombstone history, and a provider-stable
   model revision remain required before this item is complete.
   An agent-only shadow runner now freezes a closed no-action/one-proposal output contract,
   records exact requests, responses, token usage, failures, and restart outcomes in an append-only
   attempt ledger, uses one lock-protected decision window per strategy/ticker/market date, and
   routes proposal claims only through the existing non-executing admission boundary. It has no
   decision regeneration, simulator route, or execution authority. A persistent systemd timer now
   invokes the same runner after the nightly pipeline, with a hash-bound control that installation
   leaves disabled, bounded process restarts, and read-only API status. The operator enabled live
   shadow observation on 2026-09-13; that control still grants only shadow-observation continuity
   and no paper-order authority. Hybrid execution and automatic scheduling remain blocked; manual
   hybrid shadow evaluation uses a separately registered frozen algorithm candidate and veto-only
   role. The first real Trae-backed attempt returned no action and created no proposal or order;
   its cited lack of comparison history motivated the schema-v4 feature increment without changing
   or retrying that immutable decision window.
3. **Completed 2026-09-13:** add separate paper registrations and evaluation harnesses for
   agent-only and hybrid policies;
   keep existing algorithm-only registrations and scheduling unchanged.
   A source-hash-bound policy registry now defines separate reserved
   identities for agent-only dual momentum and hybrid veto-only dual momentum. Both remain at
   `shadow_proposal_only` with `execution_authority = none`; neither registration creates a
   portfolio, changes the algorithm-only `dual_momentum` book, or enters simulator scheduling.
   The hybrid policy is manual-shadow-only, uses `unmodified_algorithm_signal` on model failure,
   and names both `dual_momentum` and
   `spy_benchmark` attribution controls. New contexts, attempts, and proposals carry policy ID
   and registration hash. Existing rows remain immutable and are projected as
   `legacy_unregistered`; evaluation counts are partitioned by policy and never pooled.
   Monthly cadence admission now occurs before context construction or Trae access, recording a
   deterministic `cadence_no_action` on non-signal dates. Full return attribution and separate
   paper-book activation remain work under items 4 and 5, respectively.
4. Add deterministic proposal recomputation, risk validation, attribution, and no-action handling
   before any proposal can reach the existing simulator.
   **Started 2026-09-13:** hybrid context can now materialize the exact registered
   `dual_momentum` strategy output from the source algorithm portfolio's reconciled same-date
   cash, positions, marks, and equity without writing simulator state. Every candidate order and
   the complete candidate envelope are hashed. A separate closed veto contract permits only
   `allow` or `veto` against that exact candidate hash; it cannot introduce a symbol, side,
   quantity, order, or sell veto. Manual hybrid shadow decisions now use the same append-only
   attempt/event ledger and preserve exact replay. Transport failure, malformed output,
   candidate-hash mismatch, or an interrupted unrecorded response deterministically records the
   predeclared `unmodified_algorithm_signal` fallback; a window with no buy candidate records a
   no-model-call outcome. Hybrid scheduling, simulator writes, paper portfolio activation, full
   return attribution, and paper authority remain blocked.
   Agent-only proposal admission now independently recomputes signal-close quantity and evaluates
   policy identity, instrument eligibility/quarantine, complete registered-universe features,
   same-date signal price, policy notional and capital ceilings, stop geometry, reserved sell
   inventory, and 60-session median-dollar-volume participation. Canonical validation evidence and
   its SHA-256 are append-only with each newly evaluated proposal; failed gate names become
   rejection reasons, exact replay returns the stored evidence identity, and malformed stored
   evidence fails closed. Historical accepted rows remain immutable as `legacy_unvalidated`.
   This remains shadow-only: neither accepted nor rejected proposals create `sim_orders`, and a
   hybrid proposal envelope is rejected in favor of the candidate-bound veto path.
   A bounded `GET /agent/attribution` projection now binds every completed registered attempt to
   its policy, retained context, terminal outcome, proposal validation or hybrid candidate, and
   effective counterfactual order count. It separates model no-action, model failure, accepted or
   rejected agent proposals, hybrid allow, hybrid veto, and predeclared fallback outcomes; legacy
   attempts are counted but excluded and evidence pooling is prohibited. It deliberately reports
   return attribution as unavailable until isolated paper portfolios exist, and creates no
   portfolio, order, fill, or equity state.
   A separate read-only isolated-book verifier now defines the exact persisted registration and
   per-order ownership contracts required for those future portfolios. If such evidence is
   supplied, it verifies policy/mode/config/profile/capital/control identities, every order's
   retained decision binding, hybrid exact quantity versus agent-only bounded quantity, fill and
   position ownership, reconstructed cash and positions, and exact equity-date alignment with both
   controls. Missing books or contracts remain explicitly unavailable; malformed, mixed, pooled,
   or unreconciled evidence fails closed. An explicit, unwired schema initializer now defines only
   the two empty attribution ledgers with unique book-policy and order-decision ownership. It is
   idempotent, has not been run against the live store, and creates no portfolio or equity state.
   A pure initialization planner now emits the exact inactive `portfolios`,
   `agent_paper_book_attribution`, and cash-only opening `sim_equity` records accepted for either
   agent-only or hybrid mode. It binds every record and the
   complete plan by hash, permits only those three insert targets in one future atomic transaction,
   and explicitly protects the existing algorithm and benchmark books. It does not open DuckDB,
   create schema or books, write simulator state, schedule either policy, or add an order route;
   execution authority remains none.
   A read-only preflight now verifies one exact plan against the current database: exact required
   table schemas, global absence of the reserved portfolio and policy identities, compatibility of
   both protected control books, availability of their aligned equity rows on the exact attribution
   start date, and two identical source-state reads. It emits a hash-bound diagnostic and cannot
   write or authorize. Its operator CLI uses the actual UTC clock and cannot accept a retrospective
   planning time. The 2026-09-14 live preflight for a 2026-09-15 attribution start confirms the
   reserved identities are unused and both controls are compatible, but remains blocked because
   `agent_paper_book_attribution` and `agent_paper_order_attribution` do not exist and the controls
   cannot yet have a 2026-09-15 equity row. Creating those tables in the live store remains outside
   the current non-mutating slice.
   An operator-only migration wrapper now requires a separately verified backup bundle, its
   explicit manifest identity, an exact match between that bundle's complete logical database
   snapshot and the locked live store, and a post-DDL scope proof before commit. It can create only
   the two empty attribution ledgers; any unrelated catalog, row-count, queue, market-date, or
   active-portfolio drift rolls back. It has passed isolated-database success, idempotency,
   stale/wrong-backup rejection, incompatible-schema rejection, and forced rollback tests, but has
   not been run against the live store because no new backup destination was selected.
   The required operator sequence is explicit backup creation, independent verification, and then
   migration with the verified manifest SHA-256; schema installation alone does not create either
   reserved book or satisfy its start-date preflight.
   A separate operator-only inactive-book initializer at
   `tools.initialize_agent_paper_book` now consumes that exact plan. It requires a fresh verified
   backup of the same locked source database and a fully passing same-date preflight, then inserts
   exactly one inactive portfolio, one policy attribution contract, and one cash-only opening
   equity row atomically. Before commit it proves that catalog, jobs, market date, active portfolio
   identity, protected controls, and all unrelated row counts are unchanged, and it runs the full
   attribution verifier over the empty book and re-reads the registered policy. Any failed scope,
   attribution, or policy-identity proof rolls back all three inserts. Repeated initialization
   fails the reserved-identity gate. The initializer has no API, schedule, activation, order route,
   or execution authority and has not been run against the live store because no external backup
   destination was selected and the required control equity date has not yet arrived.
5. Advance from shadow toward automatic paper only when each authority gate is satisfied, while
   retaining human-approved exact-intent paper as a separate secondary path. The intended
   automatic-paper interaction is one authenticated UI confirmation that creates a short-lived,
   simulator-only lease with fixed policy, account, symbols, model/release, risk, duration,
   order-count, and capital bounds; it is not approval of each generated order. Do not infer broker
   or live-capital authority from paper success.
   **Started 2026-09-13:** `GET /agent/authority/readiness` now exposes a fail-closed, per-policy
   promotion checklist while keeping `current_stage = shadow`, both later eligibility flags false,
   and paper/broker routes absent. Schema v3 separates the human-approved-paper prerequisites from
   the automatic-paper prerequisites: the 60-session and approved-operation evidence gates belong
   only to automatic paper, while human-approved paper requires its own exact-intent approval
   source/verifier and still-absent execution path. Its separate review-packet gate now passes
   because bounded packet construction and retained-evidence revalidation are implemented; this
   does not satisfy the human-approval gate. The legacy top-level gate list remains the
   automatic-paper view. Both stage projections report `eligible = false` and
   `execution_authority = none` even if all current evidence prerequisites pass. The projection
   reports live-registration drift, limited mutable data provenance, the unversioned Trae model
   alias, lack of substantive decision evidence, absent isolated portfolios and return attribution,
   progress toward 60 completed sessions, recorded integrity-failure outcomes, persisted
   source-bound fault/restart adjudication, the unreleased worktree, and absence of a selected
   approval source and signer policy. The readiness evidence now also distinguishes the implemented
   source-neutral envelope/policy/authenticator interface from the still-absent selected trust
   source, production authority consumption, and production approval verifier. Schema v4 adds aggregate
   source/current-cache alignment evidence to the point-in-time data gate without changing any
   authority. Schema v5 advertised the non-authorizing discrepancy-review contract and its
   four explicit future dispositions. Schema v6 also exposes aggregate status for a separate
   append-only operator-adjudication ledger. It accepts only a fresh packet revalidated against
   retained evidence, hash-chains one decision per exact source/cache state, and treats every
   disposition as record-only; it cannot repair cache data, quarantine a ticker, or grant
   authority. Schema v7 additionally reports a separate append-only Nasdaq evidence ledger.
   Exact responses are retained with request and receipt identity, and every normalized
   ticker/date fact is re-derived from those bytes in a hash-chained observation history.
   Daily-price discrepancy packet schema v2 binds the newest such fact and compares it with both
   the retained Yahoo source observation and the operational cache. This supplies durable
   independent evidence without changing prices or making an automatic recommendation. The gate
   remains blocked because independent agreement does not supply source publication timestamps,
   stable provider dataset versions, original historical payloads, or source/cache alignment. The
   first live bounded capture on 2026-09-14 retained three exact responses and 45 derived
   observations for BIL, EFA, and SPY with zero parse or incomplete-row errors. On the disputed
   2026-09-11 facts, Nasdaq differed exactly from both Yahoo and the cache because of decimal
   precision and settled volume, but all OHLC values agreed with both within the pre-registered
   10-basis-point and one-cent verifier thresholds. Maximum Nasdaq/cache OHLC gaps were
   0.000233 bp for BIL, 0.934631 bp for EFA, and 0.130547 bp for SPY; volume gaps were
   0.474991%, 0.560100%, and 0.906331%, respectively. This evidence supports review but does not
   resolve the exact source/cache hashes or select a disposition. The operational price
   fingerprint and price/order/fill/portfolio counts remained unchanged after capture.
   The installed persistent data-capture unit now includes this independent capture step.
   Schema v8 additionally reports the separate authenticated-evidence replay-protection ledger
   while keeping the human-order approval gate blocked. The ledger writer now requires preinstalled
   schema and cannot create its own table while recording an approval observation. A
   backup-gated operator migration at `tools.migrate_agent_human_approval` can install only that
   empty table after verifying the backup manifest identity and exact logical snapshot, and rolls
   back if any unrelated catalog or database state changes. Isolated migration tests pass, but it
   has not been run against the live store; no trust source, approval grant, route, or submission
   authority was added. A separate read-only completeness verifier now captures the bounded
   approval-observation ledger twice, revalidates every retained document and source decision, and
   requires an independently supplied total observation count and latest global hash. Missing
   storage can match only trusted zero/null state; valid truncation, replacement, head mismatch,
   and concurrent change fail closed. It does not choose the independent trust source, select an
   approve observation, authenticate new bytes, consume approval, issue a lease, or grant
   authority. Schema v9 and context schema v10 bind the
   exact selected Trae catalog entry, internal `gpt-5.6-sol__max` routing key, catalog component
   marker, proxy v0.7, and Trae CLI `0.204.1` runtime. Generation requires identical pre/post
   transport attestations, and retained responses bind the same identities. This detects alias
   remapping but does not misrepresent mutable catalog metadata as an immutable provider model
   revision, so the stable-model gate remains blocked. The connector's exact proxy-version pin
   advanced from v0.6 to v0.7 only after the proxy's eighteen tests passed under the service's
   Python 3.13 runtime; arbitrary future proxy versions remain rejected. Readiness schema v11 now
   projects a sanitized, hash-verified current release manifest into the `reviewed_release` gate.
   Mechanical release eligibility and explicit authenticated human review remain distinct: even a
   clean tracked candidate is only eligible to be reviewed. A pure source-neutral verifier binds
   one exact manifest, Git commit, Git tree, readiness hash, reviewer policy, reviewer identity,
   decision, and validity window to a detached external authenticator. It requires independently
   trusted readiness and explicitly selected policy hashes. Successful verification remains
   non-persisting design evidence and is deliberately not accepted by readiness; no trust source,
   production integration, paper route, or submission authority was added. A separate
   `agent_release_review_observations` ledger now provides durable replay protection only after
   re-inspecting the current candidate and matching the externally trusted readiness hash. It
   retains canonical policy, envelope, release, and verification evidence in a global hash chain;
   exact replay is idempotent and conflicting reuse fails closed. A separate read-only completeness
   verifier captures the bounded ledger twice, revalidates every retained document, and requires an
   independently supplied total observation count and latest global hash. Missing storage can match
   only trusted zero/null state; valid truncation, replacement, head mismatch, and concurrent
   change fail closed. It does not choose the independent trust source, select an approved review,
   or make the release gate pass. The ledger deliberately requires preinstalled schema, remains
   absent from the live store, and cannot make the release gate pass.
   Release re-inspection during recording now reuses the already-open DuckDB connection instead of
   attempting an incompatible read-only connection inside the write transaction. The private
   manifest path accepts that borrowed connection only after matching DuckDB's reported database
   path to the exact no-follow-opened leaf, finding the same leaf identity among process-held
   descriptors, and preserving the parent-chain and full leaf identity across the scan. A real
   file-backed transaction regression passes, while mismatched connections and path replacement
   fail closed; normal manifest and backup scans remain read-only.
   An operator-only migration wrapper at `tools.migrate_agent_release_review` now requires a
   separately verified backup bundle, its exact manifest identity, and a complete logical snapshot
   match to the locked target before creating only the empty replay ledger. It rejects incompatible
   or nonempty existing ledgers and proves before commit that all unrelated catalog definitions,
   row counts, market date, job state, and active portfolio identities are unchanged. Forced scope
   failure rolls back the DDL. The migration has not been run against the live store and does not
   select trust, accept review evidence, satisfy the release gate, or grant execution authority.
   The live candidate remains mechanically blocked by its dirty worktree and untracked required
   files.
   A refreshed twenty-eight-case fault attestation passed on 2026-09-18 with source SHA-256
   `d8436820a93449f3d756e99d4370f39bbdadddec39a57675023cf52726ed63fc`, suite SHA-256
   `8145726e53f8c5da6f2659c4ecc20a3c9f9c18de351fc740e932fb37ed590d07`, results SHA-256
   `2ba8ab29874c096d0758a87a1f215216286136e2b704c0c1e52ed5ccd1446c42`, and run SHA-256
   `50a125aae9a89467e55fcbf3f8b23942a4f43c4ae0ea8f1f6e4eb66e5b00a6a4`;
   all twenty-eight cases passed with no indeterminate result and the run grants no execution
   authority.
   The
   `agent-shadow-state-machine-v1` drill covers duplicate-window replay, interruption before and
   after response persistence, scheduled replay, registered hybrid fallback, fail-closed
   isolated-book attribution, fail-closed separation of human-approved and automatic-paper gates,
   read-only isolated-book initialization preflight for both modes, rollback of a failed
   backup-gated attribution-schema migration, rollback of a failed backup-gated inactive-book
   initialization, rejection of self-consistent forged review facts against independently
   reloaded evidence, a read-only operator packet build/verify round trip with unchanged database
   rows, successful external-authenticator contract evaluation that still grants no authority,
   durable exact replay and rejection of conflicting authenticated-evidence identity reuse,
   rejection of valid but truncated or replaced approval-observation history against an
   independently trusted global count and head,
   rejection of Trae alias, routing, catalog, proxy, or runtime drift across generation,
   rejection of a rehashed source/cache discrepancy packet after independently reloading retained
   evidence, rejection of forged, stale, or changed evidence before a record-only adjudication is
   appended, rejection of tampered independent raw responses or derived observation chains,
   rejection of rehashed release evidence and failed detached authenticators without granting
   authority, rejection of current-release drift before authentication or persistence, rejection
   of valid but truncated or replaced release-review history against an independently trusted
   global count and head, rollback of
   failed backup-gated release-review, human-approval, and automatic-paper retention-schema
   migrations, rollback of an activation append when post-write complete-chain verification
   fails, and an
   actual transient user-systemd
   restart-on-failure probe.
   Results are append-only and become stale when the exact policy, implementation, or test identity
   changes. This is visibility only and cannot grant authority.
6. **Completed locally 2026-09-13:** define and test the first two Workstream D layers:
   the broker-neutral contract and existing-simulator adapter, followed by immutable lifecycle
   evidence and explicit uncertain-submission semantics. A structurally disabled live adapter also
   proves the fail-closed interface without introducing a network or credentials. None is exposed
   or wired as a new mutation path. Read-only reconciliation/comparison machinery is now started,
   with exact and normalized snapshots kept separately and unavailable venues retained as
   non-matches. The independent risk layer now also binds UTC observation/quote timestamps,
   quote-age limits, same-market-date observations, short decision expiry, pending-order capacity
   reservations, operational-halt state, and corporate-action clearance; exact acknowledged replay
   is side-effect free, while expired or uncertain pre-submission state fails closed. The
   deterministic snapshot assembler derives account/exposure/reservation state from stable adapter
   reads and exact retained reconciliation; its durable one-way control is halted on missing state
   and across restart. A read-only startup assessment requires exact current reconciliation, no
   unresolved uncertain submission and the halted control; it cannot report enabled authority.
   Resolved attempts remain visible in startup evidence, and a resolved open order still blocks. A
   halt-first cancel-all coordinator now persists its exact open-order plan before cancellation,
   writes an uncertain marker before each adapter call, verifies exact acknowledgements, blocks
   overlapping operations and blind retries, and records a hash-bound completion only after a
   stable empty open-order snapshot. It remains internal and unwired. A refreshed thirty-four-case
   fault attestation passed on 2026-09-17 with source SHA-256
   `07a3756a74b4a6009afde1249887bd43dd9eb7353975b10acbf80ecb94fed3a8`, suite SHA-256
   `0c167ef6b37a4710c49fdbf5601345a2f3e6ef8fd35199d39eb97e8417066098`,
   and run SHA-256
   `4b667f56c1c7b97b21b23244dc6ed4b1336c43ec988d4b7583de0d60c73dfc93`;
   all thirty-four cases passed with no indeterminate result and no execution authority. The
   paper-lease candidate contract is also defined
   and tested, but deliberately cannot issue, activate, consume, persist, renew, revoke, or submit:
   even a passing assessment carries `submission_authority = none`. A separate pure verifier now
   binds one exact intent and verified risk decision to an admitted candidate, trusted agent
   evidence, trusted usage evidence, and cumulative lease limits; its passing result is only
   `eligible_for_future_consumption` and cannot reserve or consume capacity. The proposed durable
   state machine is now documented and its transcript semantics are executable as a pure verifier:
   restart/halt/expiry/revocation invalidation, unique cumulative consumption, and the required
   atomic link to uncertain pre-call submission state are tested. An internal, unwired activation
   writer now requires the exact preinstalled retention schema, re-verifies the lease and canonical
   plan, verifies the complete global chain, compare-and-appends one `activation_recorded` row
   against the plan's expected head, and verifies the complete resulting chain before commit.
   Exact replay is idempotent; conflict, stale-head, malformed-history, and injected post-insert
   verification failures fail closed or roll back. It is tested only against isolated databases,
   has not been run on the live store, and has no trust loader, account-lock coordinator, API,
   CLI, scheduler, adapter call, consumption path, paper-order route, or submission authority.
   A second internal, unwired transaction now validates the pure consumption plan against the
   complete retained lease history, independently supplied global count/head, and a freshly
   reloaded runtime/halt binding. It atomically persists `consumption_committed`, the immutable
   broker intent, complete authority-aware risk/eligibility/plan evidence, and the existing
   `submission_started` uncertainty marker, then re-verifies the complete resulting transcript,
   cumulative limits, and all four records before commit. Exact replay is idempotent and injected
   post-write failure rolls back every record. The guarded schema migration now includes the empty
   authority-aware risk-evidence ledger but has not been run on the live store. No adapter call,
   route, CLI, schedule, paper-order route, or submission authority was added.
   Durable uncertain-submission adjudication is now implemented as an internal, non-retrying
   stable-snapshot coordinator. Read-only retained-evidence loaders now derive exact
   `PaperIntentBindings` for agent-only attempts and `HybridPaperIntentBindings` for hybrid
   attempts. The hybrid loader verifies the frozen deterministic candidate and portfolio-state
   hashes, veto-role Trae request/response or exact registered fallback path, terminal effective
   order set, and requested order membership; vetoed buys cannot load. A read-only usage loader
   now verifies one complete head-matched authority transcript, rejects valid but truncated
   prefixes and closed epochs, and derives `PaperLeaseUsage` plus the exact prior consumption,
   idempotency, and request identities without caller-supplied counters or replay summaries.
   A source-neutral, maximum-five-minute human-review packet now loads either retained intent and
   binds one exact simulator request while making registered hybrid fallback conspicuous. Its
   checksum is not a signature; it explicitly retains an unselected approval source and signer
   policy, no approval verifier or approval, and no lease, activation, route, persistence, API,
   schedule, or submission authority. Its read-only retained verifier reconstructs every field,
   rejects rehashed evidence forgery or changed source rows, and enforces generation and expiry.
   Schema v2 adds bounded independently validated price/notional/order-impact facts while clearly
   labeling model prose as untrusted rationale and excluding raw prompts and context. A separate
   stdout/stdin operator CLI forces read-only database access and cannot accept a decision.
   A pure source-neutral approval-envelope contract now binds one exact packet and request to an
   approval source, signer policy/version, signer identity, detached authenticator, one-use approval
   ID, decision, and bounded timestamps. Its explicitly supplied policy scopes signers to exact
   modes, registered policies, and reserved simulator accounts. Closed bounded strict-JSON parsers
   reject ambiguous or noncanonical policy/envelope input without selecting a trust source. It
   provides no default policy, key, trust store, algorithm, loader, CLI, API, route, or authority;
   a read-only composition reloads retained evidence before
   authentication, while even successful injected authenticator verification reports
   `human_order_approval_granted = false` and `submission_authority = none`.
   A separate append-only replay-protection store now retains only successful results from that
   composition. It binds exact policy, envelope, review packet, verification, approval, packet,
   and request identities in a globally sequenced hash chain; exact replay is idempotent and
   conflicting reuse fails closed. This is not production authority consumption and does not
   convert an authenticated approve decision into order approval. Recording now requires
   preinstalled schema and fails before authentication when the ledger is absent. An operator-only
   migration at `tools.migrate_agent_human_approval` requires a separately verified backup, the
   exact backup-manifest identity, and an exact logical snapshot match before creating only the
   empty `broker_human_paper_approval_observations` table. It rejects incompatible or nonempty
   ledgers and proves that unrelated catalog definitions, row counts, market date, job state, and
   active-portfolio identities remain unchanged; failed post-DDL scope verification rolls back.
   Isolated success, idempotency, rejection, and rollback tests pass. The migration has not been
   run against the live store and cannot select trust, grant approval, create a route, or create
   submission authority.
   A read-only runtime/control loader now supplies a process-local non-persisted random epoch and a
   twice-stable verified halt-chain anchor; process restart, missing or tampered control state, and
   a chain advance during capture fail closed. A pure authority-aware risk projection now binds the
   candidate assessment, complete open transcript, current runtime/control evidence, and original
   halted snapshot. It preserves the historical halt and remains unwired. A second pure evaluator
   now re-verifies that projection and runs the same twenty standard gates against an ephemeral
   snapshot whose control flag alone is clear. Every other gate remains effective, and the
   original halted snapshot and control identity remain bound. Its result is a distinct
   non-submittable dataclass rather than the ordinary broker-ledger risk decision, reports no
   submission integration or authority, and remains unwired. It also retains the exact computed
   notional and candidate, usage, transcript, runtime, and control identities. A pure atomic
   consumption planner now re-verifies that evidence with the exact retained agent-only or hybrid
   intent and broker request, proves that consumption, idempotency, and request identities are
   unused in the complete transcript, recomputes capacity, and emits canonical expected
   broker-intent, future `submission_started`, and transcript-v2 `consumption_committed`
   commitments under one bundle hash. The current ledger does not store the proposed
   started-event hash, and the planner has no persistence, transaction, adapter, submission, API,
   or schedule surface. A complementary pure activation planner now verifies the admissible lease
   assessment, schema-v2 startup artifact, current process/control evidence, and the durable
   startup loader's externally head-bound complete history. It rejects stale evidence, changed
   halt state, and reused lease identity, and emits only exact future `activation_recorded` bytes.
   It binds the expected prior global row count/head but has no writer, schema creation,
   transaction, adapter, API, schedule, or authority surface. The remaining
   human-trust loader still requires an operator-selected approval source, signing mechanism, and
   signer policy and must not be invented. The source-neutral envelope contract is not that trust
   loader. Do not consider even an unwired writer before that trust selection and the other listed
   blockers are resolved. A pure startup epoch scanner now verifies complete retained transcript
   bundles, rejects missing heads, tampering and duplicate epoch identities, classifies
   prior-process epochs as restart-invalidated, and blocks if any current-process epoch still
   appears open. A separate read-only durable startup loader now recognizes only an exact
   pre-existing retention-table schema, captures all rows twice, verifies the store-wide sequence
   and hash chain against an externally trusted total row count and latest global head,
   reconstructs every canonical lease/event bundle, and feeds every epoch to that scanner.
   A missing or empty store is safe only under a trusted zero count and null head; valid prefixes,
   omitted and rechained epochs, gaps, malformed payloads, identity drift, and concurrent changes
   fail closed. The loader cannot create the retention schema, write authority state, or grant
   startup or submission authority and remains unwired. An operator-only migration at
   `tools.migrate_agent_paper_authority_store` can install only that exact empty retention table
   and the empty authority-aware risk-evidence table after
   verifying a separate backup, its manifest identity, and a complete snapshot match. It rejects
   incompatible or nonempty stores, proves all unrelated catalog and logical database state
   unchanged, and rolls back on post-DDL scope failure. Isolated migration tests pass; it has not
   been run against the live store and adds no runtime activation, adapter integration, route, or
   submission authority. Production trust loading, account-lock integration, and an independent
   trust/backup policy for the global retention head remain blocked;
   external broker-paper work remains prohibited on
   this host and requires separately selected personal infrastructure.
