# Automatic-paper authority state-machine design

**Status:** reviewed design contract, pure activation and atomic-consumption planners, pure
transcript verifier, read-only agent-only, hybrid, usage, runtime/control, startup-readiness, and
durable startup evidence loaders, a pure startup epoch scanner, an isolated transactional
activation-evidence writer, and a source-neutral human-approval envelope/policy verifier
interface. No selected human trust source or production signer policy, trust loader, activation
command, consumption coordinator, adapter integration, route, or schedule exists. Nothing in this
design grants current paper-order authority.

## Scope and invariants

This state machine is only for future automatic execution in isolated simulator portfolios
registered as `agent_only` or `hybrid`. It does not replace or alter:

- algorithm-only portfolio registrations, scheduling, signals, or fills;
- the append-only one-way broker halt chain;
- deterministic pre-trade risk;
- the current shadow proposal and hybrid-veto ledgers; or
- the prohibition on external brokers, credentials, and live capital.

The model remains a proposal or veto source only. It cannot issue a lease, select trusted hashes,
activate authority, consume capacity, invoke an adapter, or resolve uncertain state.

The intended human interaction for automatic paper is one explicit UI confirmation such as
**Enable automatic paper**, not approval of every generated order. A future authenticated
confirmation would issue one simulator-only lease bounded to the exact release, model revision,
policy, account, symbols, risk identities, duration, and order/capital limits. Deterministic
validation would then govern qualified automatic orders during that lease. The existing
exact-intent approve/reject packet remains a separate, secondary supervised-paper flow and is not
on the critical implementation path for the automatic transaction machinery.

## Why authority is a separate epoch

`server/broker_risk_control.py` intentionally has no clear operation. Missing state and every
recorded event mean halted. A future implementation must not mutate history or add a disguised
`clear_halt`.

Instead, one activation would create a short-lived authority epoch anchored to:

- the exact latest verified halt-chain event count and hash;
- a fresh, hash-bound `reconciled_halted` startup assessment;
- an externally trusted operator-enabled lease and candidate assessment;
- one process-start runtime epoch;
- one simulator account and one `agent_only` or `hybrid` mode.

The historical halt remains true. The pure, unwired authority-aware projection in
`server/broker_paper_risk_projection.py` proves that the exact anchor would serve as the epoch
baseline only while every lease gate still passes. It retains
`historical_operational_halt = true`, reports `risk_evaluation_implemented = false`, returns a
distinct type that the current risk evaluator rejects, and never mutates the snapshot or halt
chain. `server/broker_paper_risk_evaluation.py` is the next pure handoff: after re-verifying that
projection, it evaluates the same twenty standard gates against an ephemeral copy whose control
flag alone is clear. The original halted snapshot and control hash remain bound in the result.
Its output is a distinct dataclass rather than the ordinary risk-decision dictionary accepted by
the broker ledger. It retains the exact computed order notional and the candidate, usage,
transcript, runtime, and control identities used in the evaluation, reports
`submission_integration_implemented = false` and `submission_authority = none`, and cannot be
submitted. Any later halt event advances the chain and irreversibly invalidates the epoch. Current
risk assembly remains halted.

The runtime epoch must be regenerated at every process start and must not be restored from the
database. A restart invalidates all prior activations. Reactivation requires a new lease ID,
fresh human approval, fresh startup/reconciliation evidence, and a new activation event; an old
lease is never resumed.

## Release review boundary

`server/agent_release_readiness.py` implements the non-authorizing release prerequisite as two
separate proofs. First, it verifies and sanitizes the current release manifest. A clean, complete,
fully tracked manifest can establish mechanical release eligibility, but it cannot establish
human review. Second, its pure review verifier accepts only an explicitly supplied reviewer
policy, an independently trusted release-readiness hash, and a detached external authenticator
over one exact manifest, Git commit, Git tree, reviewer, decision, and bounded validity window.

This verifier does not select a trust source, key, authenticator algorithm, reviewer policy, or
trusted readiness hash. It does not persist review evidence, feed a passing result into
`GET /agent/authority/readiness`, issue a lease, activate an epoch, or grant submission authority.
Readiness schema v11 exposes the sanitized manifest projection and aggregate status from the
separate `agent_release_review_observations` ledger while keeping `reviewed_release` blocked. The
ledger re-inspects the exact current release before authentication, requires the independently
trusted readiness hash, retains canonical policy, envelope, release, and verification evidence,
and provides a global hash chain with exact-idempotent replay and conflicting-identity rejection.
Its read-only completeness verifier captures the bounded ledger twice, revalidates every retained
document, and requires an independently supplied total observation count and latest global hash;
missing storage can match only trusted zero/null state, while valid truncation, replacement, head
mismatch, and concurrent change fail closed. The verifier does not select an approved review or
make the release gate pass. The schema must be installed separately before recording, and it is
not initialized in the live store. A future authority writer must independently load durable
trusted review evidence and revalidate the exact release before activation; a clean Git worktree
or a stored observation alone must never satisfy the gate.

## Proposed immutable events

One future append-only table would store a canonical payload and SHA-256 for each event, keyed by
`(lease_id, event_sequence)`. Every event binds the lease hash, account, mode, UTC time, prior
event hash, and `submission_authority = none`.

| Event | Required additional bindings | Meaning |
|---|---|---|
| `activation_recorded` | candidate assessment, startup assessment, control anchor, runtime epoch | Operator-enabled candidate was recorded for this one bounded epoch |
| `consumption_committed` | unique consumption key, broker idempotency key, eligibility, exact request, authority-aware risk evaluation, order notional, resulting counters, exact `submission_started` commitment | Capacity was conservatively spent before an adapter call |
| `revocation_recorded` | unique revocation key, reason, strictly later halt-chain anchor | Epoch is terminally revoked |

Activation occurs at most once per lease. Consumption keys, broker idempotency keys, and request
hashes are globally unique within the lease. Revocation is terminal. Timestamps never move
backward, and activation and consumption must occur before the lease expiry.

`server/broker_paper_authority_transcript.py` verifies this proposed transcript and recomputes
order-count and notional use. It is deliberately pure: it has no DuckDB, adapter, clock, network,
or mutation dependency, and reports `submission_authority = none` even when the design state is
`activation_window_open_design_only`. Transcript schema v2 binds
`risk_evaluation_sha256`, preserving the type separation from ordinary broker-risk decisions.

`server/broker_paper_consumption_plan.py` is the pure pre-commit bridge. It re-verifies the
candidate assessment, retained agent-only or hybrid intent, complete usage evidence, exact broker
request, and distinct authority-aware risk evaluation. It proves that the consumption key,
idempotency key, and request hash are unused in the verified transcript, recomputes cumulative
capacity, and emits canonical expected broker-intent, `submission_started`, and
`consumption_committed` commitments under one bundle hash. The started-event hash is explicitly a
commitment to the canonical marker; the existing broker ledger stores that marker's fields but
does not have a hash column. The plan has no writer, transaction, adapter, or submission surface
and reports `submission_authority = none`.

`server/broker_paper_consumption_store.py` is the internal, unwired atomic pre-call coordinator.
It requires exact preinstalled authority, authority-aware risk-evidence, broker-intent, and
submission-event schemas. Inside one transaction it re-verifies the complete authority chain
against an independently supplied global count/head, re-derives lease usage, re-reads the current
runtime/halt binding, and persists the canonical `consumption_committed` event, broker intent,
full authority-aware risk evaluation and plan evidence, and `submission_started` uncertainty
marker. It then re-verifies the complete resulting transcript, cumulative limits, risk ledger,
intent, and marker before commit. Exact four-record replay is idempotent; partial replay, changed
halt state, stale evidence, stale global head, and post-write verification failure fail closed.
The coordinator stops before any adapter call and exposes no route, CLI, or schedule.

## Activation transaction

Production activation may occur only under the repository's exclusive writer discipline and one
account-scoped advisory lock:

1. Load the lease from a human-controlled trust source. API/model-provided hashes are never trust.
2. Recompute the exact lease candidate assessment from retained current evidence.
3. Require simulator environment, allowlisted account, registered mode, reviewed release,
   provider-stable model revision, automatic-paper evidence gate, and unexpired lease.
4. Re-run startup assessment around stable adapter reads and require `reconciled_halted`.
5. Read and verify the latest one-way halt-chain anchor.
6. Bind the current non-persisted process-start epoch.
7. In one database transaction, reject any prior event for the lease and append exactly one
   `activation_recorded` event.
8. Commit without calling an adapter.

`server/broker_paper_activation_plan.py` implements the pure pre-commit portion of this
sequence. It independently verifies the admissible lease assessment, complete startup-readiness
artifact, current process/control binding, and durable startup scan. The scan must carry the
externally trusted global retention row count and head verified by the read-only startup-store
loader. The plan binds that expected prior global head, rejects reuse of a retained lease identity,
requires fresh startup and scan evidence, and emits the exact proposed `activation_recorded`
event and hashes. It cannot create the retention table, append an event, acquire a lock, invoke an
adapter, or grant authority.

`server/broker_paper_authority_store.py` implements only step 7 as an internal test-harness
transaction. It requires the exact preinstalled retention schema, re-verifies the plan and lease
binding, verifies the complete existing global chain, compare-and-appends against the plan's
expected count and head, and re-verifies the complete resulting chain before commit. Exact replay
is idempotent, while stale heads, malformed history, and conflicting lease or activation identity
reuse fail closed. A failed post-insert verification rolls back. Its result explicitly keeps
runtime activation, consumption, adapter integration, HTTP, scheduling, the paper-order route, and
submission authority absent. There is no production caller, account lock integration, migration
against the live store, or command that can invoke it.

## Consumption and future submission transaction

Eligibility by itself is not a reservation. To avoid concurrent overspend and crash ambiguity,
future consumption must share one transaction with the broker lifecycle's pre-call marker:

1. Hold the account/lease lock and begin one DuckDB transaction.
2. Verify the entire authority event chain and recompute current usage from events.
3. Require the same runtime epoch and unchanged halt-chain anchor.
4. Re-load and verify the retained agent-only proposal or hybrid candidate/outcome. Callers may
   not designate a trusted hash.
5. Recompute the pure atomic consumption plan using current time and retained evidence.
6. Re-verify the exact authority-aware risk evaluation and its expiry.
7. Reject duplicate consumption key, broker idempotency key, or request hash.
8. Append `consumption_committed`, the immutable broker intent, the authority-aware risk
   evaluation, and
   `submission_started` atomically. The consumption event binds the exact started-event hash and
   requires submission state `uncertain`.
9. Commit the transaction before invoking the simulator adapter.
10. Invoke the adapter at most once, then persist an exact acknowledgement in a separate
    transaction using the existing broker lifecycle contract.

Steps 2 through 8 are implemented in the isolated pre-call coordinator, except that account/lease
lock ownership is not yet integrated. Steps 9 and 10 are intentionally not wired: no runtime
caller can invoke the simulator after this commit.

Crash outcomes are intentionally conservative:

| Failure point | Durable state | Permitted recovery |
|---|---|---|
| Before the atomic pre-call commit | No consumption and no submission marker | A fresh attempt may re-evaluate |
| After commit, before/during adapter call | Capacity consumed; submission uncertain | No retry; reconcile venue state |
| After adapter acknowledgement | Capacity consumed; submission acknowledged | Exact replay returns retained state |

An uncertain attempt continues to consume lease capacity. Refunding capacity would create an
unsafe retry channel and is prohibited.

## Revocation and emergency stop

Revocation is halt-first:

1. Append a new one-way operational halt.
2. This immediately invalidates the active epoch because the control chain advanced.
3. Run the existing halt-first cancellation coordinator for open orders.
4. Append `revocation_recorded` only after binding the strictly later halt anchor.

Failure to write the revocation record does not preserve authority: the advanced halt chain is
already sufficient to invalidate the epoch. Cancellation uncertainty remains a startup blocker.

## Required evidence loaders

The current pure contracts accept caller-supplied trusted hashes so their logic can be reviewed
and tested. Production use requires internal loaders that derive those values from retained state:

- Human trust loader: validates approval authenticity, scope, expiry, and signer authorization.
- Human approval contract: **implemented pure and source-neutral** in
  `server/broker_human_paper_approval.py`; it binds a detached authenticator to one exact review
  packet/request and requires an explicitly supplied signer policy and authenticator verifier.
  Its policy scopes signer identities to modes, registered policies, and reserved simulator
  accounts. Closed bounded strict-JSON parsers reject duplicate/unknown fields, noncanonical
  timestamps and authenticator encoding, malformed scope lists, and oversized input without
  selecting or trusting a source. A read-only composition reloads the packet from retained decision
  evidence before authentication, rejecting even a rehashed packet forgery before the
  authenticator callback.
- Authenticated-evidence replay protection: **implemented, durable, and non-authorizing** in
  `server/broker_human_paper_approval_store.py`. It accepts only the successful retained-evidence
  authentication result above, retains the exact policy, envelope, review packet, and verification,
  globally sequences and hash-chains observations, and makes approval ID, envelope, packet, and
  request identities unique. Exact retained replay is idempotent; conflicting reuse, omitted or
  changed source evidence, malformed payloads, and chain tampering fail closed. Both approve and
  reject decisions can be observed. This is evidence replay protection, not executable authority
  consumption: every record still reports no human approval and no submission authority. A
  separate read-only completeness verifier captures the bounded ledger twice, revalidates every
  retained document and source decision, and requires an independently supplied total observation
  count and latest global hash. A missing ledger can match only trusted zero/null state; a valid
  truncated prefix, replacement, trusted-head mismatch, or concurrent change fails closed. The
  verifier deliberately does not choose a trust source, select an approve observation, validate a
  new authenticator, issue a lease, or consume approval.
- Agent-only loader: **implemented read-only** in `server/agent_paper_evidence.py`; it verifies the
  recomputable decision-window identity, frozen policy and Trae identities, retained context,
  request and response sequence, normalized proposal, accepted terminal result, deterministic
  validation payload, and proposal audit row, then derives `PaperIntentBindings` and its hash.
- Hybrid loader: **implemented read-only** in `server/agent_paper_evidence.py`; it verifies the
  recomputable decision-window identity, frozen policy and veto-role Trae identities, deterministic
  candidate and portfolio-state hashes, exact model allow/veto or registered fallback path,
  terminal result, effective order set, and exact surviving-order membership, then derives
  `HybridPaperIntentBindings` and its hash. A vetoed buy cannot load.
- Usage loader: **implemented read-only** in `server/broker_paper_usage.py`; it requires a trusted
  retained event count and head identity, verifies the complete authority transcript, rejects a
  valid but truncated prefix and every closed epoch, and derives `PaperLeaseUsage` plus the exact
  prior consumption, idempotency, and request identities; callers never supply counters or
  replay-history summaries.
- Runtime/control loader: **implemented read-only** in `server/broker_paper_runtime.py`; it creates
  one process-local, non-persisted random epoch and captures the latest complete verified halt-chain
  anchor twice. Missing, tampered, or changing control state fails closed.
- Durable startup loader: **implemented read-only** in
  `server/broker_paper_startup_store.py`; it recognizes an exact pre-existing retention-table
  schema, captures all rows twice, verifies a store-wide sequence and hash chain against an
  externally trusted total row count and latest global head, reconstructs canonical lease/event
  bundles, and feeds every epoch to the pure startup scanner. A missing or empty table is accepted
  only with an externally trusted zero count and null head. Valid prefixes, omitted and rechained
  epochs, malformed payloads, identity drift, and concurrent changes fail closed.
- Startup-readiness verifier: **implemented pure** in
  `server/broker_startup_readiness.py`; schema v2 exposes the account-active fact and declared
  reconciliation-age limit, normalizes UTC timestamps, and recomputes all blocker reasons,
  control identity, recovery-list consistency, status, and artifact hash. A rehashed semantic
  forgery cannot become activation evidence.
- Activation planner: **implemented pure** in
  `server/broker_paper_activation_plan.py`; it joins the verified candidate, startup readiness,
  durable global-head-bound startup scan, and current runtime/control evidence into exact future
  activation bytes. It remains non-persisting and non-authorizing.
- Activation evidence writer: **implemented internally and unwired** in
  `server/broker_paper_authority_store.py`; it transactionally compare-and-appends one planned
  activation to an exact preinstalled store, verifies the complete chain before and after the
  write, and supports only exact idempotent replay. It has no schema migration, trust loader,
  account-lock coordinator, route, schedule, adapter call, consumption path, or submission
  authority.
- Atomic pre-call coordinator: **implemented internally and unwired** in
  `server/broker_paper_consumption_store.py`; it atomically persists consumption, complete
  authority-aware risk and plan evidence, broker intent, and the uncertain submission marker, then
  re-verifies the resulting state. It does not call the simulator. The guarded authority-store
  migration can install its empty risk-evidence table, but has not been run on the live database.

The source-neutral human-approval contract, its separate non-authorizing replay-protection ledger
and externally head-bound completeness verifier, and the agent-only, hybrid, usage,
runtime/control, startup-readiness, and durable startup loaders are the implemented items in this
list. The pure activation and atomic-consumption planners, isolated activation-evidence
transaction, and isolated atomic pre-call transaction are also implemented. They remain unwired
from runtime activation, adapter submission, HTTP, CLI, and scheduling paths. The approval contract
deliberately has no default policy, bundled key, trust store, algorithm implementation, or
authority result. Human trust loading, independent policy for the approval-history head, and
production one-use authority issuance remain unimplemented until an enablement source,
authentication mechanism, and policy are selected. The trusted global retention head also
requires an independent future trust/backup policy before runtime integration.

## Recovery blockers before production integration

The broker submission ledger now has a durable, internal adjudication record for an uncertain
submission. `server/broker_submission_resolution.py` captures a twice-identical complete adapter
snapshot, requires an explicit durable halt event, matches immutable request terms and venue
identifiers, and classifies the attempt as open, filled, terminally partial-filled, or not
observed. The full snapshot and control identity are retained and hash-bound. Resolution never
changes the underlying submission from `uncertain`, never calls submit or cancel, and always
sets `retry_permitted = false`; an absent order is permanently `not_observed_burned`, not safe to
retry. Startup can distinguish adjudicated attempts from unresolved ambiguity, but an adjudicated
open order remains blocking. This closes the retained-adjudication prerequisite only; it does not
create an activation or submission path.

The writer is also blocked until all of the following are available:

- a reviewed, recoverable release;
- a provider-stable Trae model revision;
- a human trust source and signer policy;
- isolated simulator books with full mode-separated return attribution;
- the complete 60-session authority evidence gate;
- a reviewed consumption/submission integration design for the pure authority-aware risk
  evaluation, without making its distinct design evidence acceptable to the broker ledger until
  every authority prerequisite passes;
- a reviewed durable writer and independent trust/backup policy for the startup loader's global
  retention count and head; the read-only loader and scanner already reject missing, truncated,
  malformed, duplicate, drifted, concurrently changing, or still-open authority epochs; and
- recovery drills for pre-commit crash, post-commit/pre-call crash, timeout, acknowledgement
  loss, duplicate process, concurrent intents, halt race, expiry race, restart, and tampering.

Until those blockers are closed, the next implementation layer must remain a pure verifier or an
unwired test-only ledger. It must not be connected to `server/main.py`, the agent runners,
`server/tickets.py`, any scheduler, `sim/league.py`, or an adapter submission call.
