# Stage 2: personal-host IBKR paper execution

**Draft for `docs/design/stage2-broker-paper.md`; the challenger lab's Stage 2 design workstream
(P16 W8), documents only.** This design is proposed.
It authorizes no account creation, credentials, broker connection, installation, order, or capital
on the current host. The separate execution plan in `execution-layer-plan.proposed.md` must be
approved before implementation. Stage 2 follows a prospective Stage 1 policy pass, not a historical
replay, filing IC slice, or an OHLCV fill-calibration result.

## Objective and admission

Run the same frozen decision policy on the owner's personal hardware, submit its deterministically
sized orders to an isolated IBKR paper account, attribute every broker order, reconcile economic
state, and measure the difference from the simulator for one to three months. Preserve every
original simulator cohort. The new broker-paper cohort has its own registration, account identity,
execution contract, opening balance, model identity and reporting namespace.

This is future work, explicitly not work for now. Before any later work starts, the owner must
select personal hardware, an IBKR paper account, model identity acceptable for Stage 2, and an
execution-layer plan. Record the instrument
and tax review called for in `docs/product.md`: US dividend withholding and US-situs estate exposure
can favor UCITS ETFs for allocation sleeves. **Verify before the instrument decision:** there is
no comprehensive US–Singapore income-tax treaty reducing ordinary US dividend withholding, so a
Singapore-resident non-US beneficial owner generally faces 30% withholding on US-source dividends
even with a valid W-8BEN (the form establishes foreign status; it does not itself create treaty
relief). Verify the treatment of the particular investor, instrument and distribution; exceptions
are not assumed. For a nonresident noncitizen, US-situs holdings can create US estate-tax filing/
exposure above roughly US$60,000 of US-situs assets; that is not a blanket tax rate or a guarantee
of liability below/above one number. Verify domicile, treaty status and indirect fund exposure
with qualified tax advice. Stage 2 simulated paper orders create no real securities trades or
investment-tax consequence, but any real account funding/subscription expense is separate. Freeze
US-listed versus eligible UCITS instruments before the cohort. A substitution is a new policy/cohort;
it is not a deployment detail. The S$10,000 envelope is a single owner capital envelope; the
profitability evidence loop (P15)
US$10,000 comparisons are counterfactual simulator books, not separately deployable allocations.

Broker-paper success is operational and measurement evidence. IBKR paper fills are simulated by
the broker and may differ from live routing, auction liquidity, queues, partial fills and market
data. They cannot establish a tradable edge or authorize Stage 3. Live capital separately requires
the owner-approved limits and capital steps and a provider-issued immutable model revision.

## Owner decisions

These are concrete recommendations for the owner to select when approving the execution plan,
not authorizations given by this design. Stage 2 implementation can prepare read-only fixtures and
packages first; account, environment, funding and subscription actions require the recorded choices.
The broker-paper model recommendation extends the existing observable **paper** identity policy;
it does not impose the immutable-revision requirement intended for real capital.

| Decision and options | Recommendation and reason | Needed by | What it blocks |
|---|---|---|---|
| Host: personal always-on Linux mini-PC; personal laptop; personally billed cloud VM | Personal always-on Linux host with reliable storage/network and optional UPS, separate from routine laptop use; owner controls restart and Gateway access | Stage 2 deployment | Installing Gateway/services and trusted state roots |
| Account opening/funding: eligible existing personal IBKR account; new personal IBKR Singapore account; defer | Use an eligible existing personal account if available; otherwise owner opens an individual account with the applicable Singapore entity and funds only the verified minimum required for paper/data access. Verify whether real-trade permissions can remain disabled; if they cannot, require account separation and structural live-account rejection | Stage 2 read-only account verification | Paper account provisioning, entitlements and identity binding; funding is not trading-capital authority |
| Account type: cash; margin; defer | Prefer an isolated cash paper account to prevent accidental shorts; verify that the required paper setup can be cash and still support the registered auction orders | Stage 2 contract registration | Buying-power, settlement, short rejection and risk semantics |
| Commission plan: fixed; tiered; defer | Select one plan after comparing the owner's eligible schedule and market-data costs; bind it before calibration rather than inferring fees from paper fills | Stage 2 registration | Fee attribution, simulator twin and budget |
| Market data: live account's eligible subscriptions; explicitly delayed/unsubscribed data; defer | Use the smallest verified live-account subscription covering the frozen universe and required quote fields. Owner approves recurring spend first; delayed data may test connectivity only | Stage 2 execution/measurement rehearsal | Fresh risk marks, bid/ask validation and paper-fill comparison; no assumed free consolidated feed |
| Instruments: original US-listed Stage 1 universe; eligible UCITS universe; separately registered sleeves | Preserve the exact passing US-listed universe for its paper execution comparison; evaluate UCITS for allocation/live-capital sleeves before registering those separate cohorts. Changing markets would confound the paired result | Before each Stage 2 cohort; tax/instrument decision before Stage 3 | Cohort registration, contract resolution, order capabilities and comparable results |
| Account representation: USD-only sleeve; new multi-currency contract | Isolated USD-only sleeve with USD instruments and cash; reduces FX/accounting scope. Any non-USD broker balance still needs explicit attribution, never hidden by the projection | Stage 2 contract and risk registration | Balance schema, FX assumptions and reconciliation |
| Model for broker-paper: observable personally owned identity; immutable provider revision now; no model | Extend the existing observable, drift-checked paper identity to broker-paper in the approved mandate; it enables operational evidence while retaining immutable provider revision as a Stage 3 prerequisite | Stage 2 model-enabled rehearsal | New broker-paper policy calls; no implicit permission for live capital |
| Paper risk envelope: rehearse proposed −3% daily / −10% drawdown; tighter limits; retain simulator limits only | Rehearse −3% daily / −10% drawdown plus any stricter policy limits in one isolated paper sleeve; exercises intended halts without claiming the owner has approved live limits | Stage 2 activation | RiskPolicy values and halt tests; Stage 3 needs separate owner approval |
| Exit response: cancel entries only/keep existing sells; cancel all; automatic flatten | Cancel entries only and keep existing risk-reducing sells; no automatic flatten until a reduce-only rehearsal passes. This avoids cancelling protection or creating a duplicate exit while holdings are uncertain | Stage 2 submission authority | Halt response, cancel/fill-race handling and recovery tests |
| Failure response: push alerts; on-demand investigation; scheduled digest | On-demand agent investigation with retained local evidence and no push alerting (owner decision, 2026-10-02) | Stage 2 operations | No alert credentials, routing, or response SLA |
| Off-host watcher: separate service; another personal device; none | None for now; any future watcher needs a separate owner decision and cannot create order authority | Stage 2 operations | Local fail-closed behavior and later outage rehearsal |
| Budget ceilings: host; data; account/funding; alerts | Approve separate one-time and recurring ceilings before any purchase, subscription or account action | Before implementation/deployment | Spending and deployment approval |

## IBKR prerequisites and quirks (verify at implementation)

Every row below is **VERIFY**, not a current entitlement or API guarantee. The implementation must
retain dated official documentation/account evidence for the selected IBKR entity, account type,
API and instruments before admitting the corresponding behavior. No broker endpoint was called
for this design.

| Item | Status | Required verification and implementation consequence |
|---|---|---|
| Gateway lifecycle / 2FA | **VERIFY** | Daily scheduled restart and periodic full authentication/2FA can interrupt unattended sessions. Verify whether the paper username requires 2FA and whether an owner phone login displaces Gateway under the one-session-per-username rule. Freeze the tested login sequence and maintenance window; IBC cannot be assumed to bypass 2FA, and reconnect returns to read-only reconciliation |
| Singapore account relationship | **VERIFY** | Paper access is generally tied to an approved/funded live brokerage account; confirm applicability, entity (IBKR Singapore), minimum funding, cash-versus-margin account type and paper provisioning for this owner. Verify that real-trade permissions may remain disabled; no account is opened/funded by this plan draft |
| Paper market-data entitlements | **VERIFY** | Paper data is typically shared from the associated live account's subscriptions/permissions; confirm sharing/concurrent-login limits, costs, venue coverage and any delayed-data mode. Do not presume paper supplies an independent free real-time feed |
| Commission plan | **VERIFY** | Fixed versus tiered pricing, minimums, exchange/regulatory fees and paper fee reporting affect `fee_bp`. Bind selected schedule and actual commission reports; a missing paper fee is pending/unavailable, never zero |
| MOO/LOO eligibility and deadlines | **VERIFY** | Establish exact exchange/route-specific entry, modify and cancel cutoffs, broker buffer and accepted order types/TIF. No universal 09:30 cutoff; a late cancel or order must be rejected/expired according to the registered rule |
| Fractional auction quantities | **VERIFY** | Confirm whether MOO/LOO supports fractional quantities for each contract; otherwise whole shares only with deterministic rounding before risk/registration. Do not silently route fractional auction orders as regular market orders |
| Paper auction simulation | **VERIFY** | Paper auction fills are broker simulations, not exchange queue participation; document supported behavior, partial fills and differences from live auction matching. Operational passes are not proof of executable capacity |
| TWS API versus Web API | **VERIFY** | Recommend TWS API through personal Gateway: fits persistent order/callback lifecycle and existing broker-neutral contract. Verify supported API version and entitlement; Web API has different session/auth semantics and would be a distinct registered transport, not a fallback |
| Paper reporting and recovery history | **VERIFY** | Confirm TWS execution/completed-order retention and whether Flex Query and statements are available for this paper account, including coverage, latency and correction fields. No assumed history window or immediate Flex availability |

## What already exists, and what does not

The source inventory was read from `server/broker_*`, plus the simulator and disabled-live
adapters. Despite the shorthand “IBKR adapters,” the checkout contains **broker-neutral inert
infrastructure, not an IBKR network transport**. Do not claim that a configuration switch connects
it to IBKR. The following modules provide reusable contracts and tested design behavior:

| Existing code | Behavior read from the implementation | Proposed reuse / gap |
|---|---|---|
| `broker_contract.py` | Typed account, position, order and fill protocol; `SubmitOrderRequest` permits only market/DAY, no extended hours; account environments simulator/paper/live-disabled | Reuse failure taxonomy; add a new versioned paper execution contract rather than force P15 limit-on-open into market/DAY |
| `simulator_broker_adapter.py`, `disabled_live_broker_adapter.py` | Local simulator boundary and structurally disabled live surface | Fixtures and paired simulator adapter remain; live-disabled surface must still reject every mutation |
| `broker_submission.py::submit_once`, `broker_ledger.py` | Durable `uncertain` marker before the external call, acknowledgement afterward; exact replay returns original, uncertain replay does not resubmit | Preserve that transaction order in the new runtime; DB writer is closed/released around network waits |
| `broker_submission_resolution.py::resolve_uncertain` | Stable snapshot adjudication; absent-at-venue burns the old idempotency key rather than making it retryable | Resolve using orderRef/permId/execution evidence; no blind retransmission after timeout |
| `broker_reconciliation.py` | Complete bounded account/positions/orders/fills capture twice, exact comparable economic state, classified differences | Reconcile broker accounting to a broker-fill mirror. Raw simulator price differences are performance attribution, not an accounting break |
| `broker_startup_readiness.py` | Reconciles complete state before/after startup and blocks unresolved submissions, cancellations and emergency stops | Use before admitting an execution epoch; incomplete broker pagination/history means not ready |
| `broker_risk.py`, `broker_risk_snapshot.py` | Pure risk evaluation over explicit policy, identity, marks, performance and reconciliation evidence | Extend only for an approved paper contract; keep deterministic risk independent of the model |
| `broker_risk_control.py`, `broker_emergency_stop.py` | Append-only one-way halt, missing state halted; halt-first cancel-all through an explicit adapter | Keep durable halts. There is no existing general resume, automatic liquidation or authorization path |
| `broker_paper_lease.py`, `broker_paper_intent.py`, `broker_paper_usage.py` | Pure proposed leases and eligibility; usage derived from verified complete transcripts | Reuse design validation, not treat a passing value as live capability |
| `broker_paper_runtime.py` | Current-process nonce/epoch, twice-stable halt anchor, execution_authority none | Restart must invalidate old runtime authority; do not restore a nonce from backup |
| `broker_paper_authority_transcript.py`, `broker_paper_startup_scan.py`, `broker_paper_startup_store.py` | Verify retained epochs and closed/invalidation state against a trusted retained head | Recovery evidence, with trust binding supplied by a future approved runtime |
| `broker_paper_activation_plan.py`, `broker_paper_authority_store.py` | Pure activation plan and test-harness persistence; evidence remains non-submittable | Production activation writer/coordinator does not yet exist |
| `broker_paper_consumption_plan.py`, `broker_paper_consumption_store.py` | Plan and test-harness atomic pre-call retention of consumption, risk and uncertainty; no adapter call | Reuse atomic pattern; don't call a test-harness method as a production authorization workaround |
| `broker_paper_risk_projection.py`, `broker_paper_risk_evaluation.py` | Distinct design-only types reinterpret an open paper epoch, cannot be used by current submission | New explicit integration and tests are required; no type casting into normal risk decisions |
| `broker_human_paper_review.py`, `broker_human_paper_approval.py`, approval store | Exact-intent review/authentication/replay-protection evidence, no submission authority | Relevant to owner mandate and exceptional recovery; does not require routine approval of every autonomous paper order |
| `broker_risk_fault_drills.py`, existing broker tests | Inert boundary fault exercises | Extend with transport contract, pagination, disconnect and real paper evidence after approval |

`BrokerFill` currently has only an `occurred_on` date and nonnegative `total_cost_bps`. Real paper
measurements need a timestamp and signed price improvement; do not clamp improvement to zero to
fit the old type. Likewise one currency/cash field is insufficient for a multi-currency IBKR
account. Either admit a USD-only isolated sleeve and explicitly reconcile other balances, or
approve a new account/cash contract. Never discard an unexpected currency or position.

## Personal-host release and configuration

Propose an owner-controlled Linux host with reliable storage, clock synchronization and network,
and a supported IBKR TWS/Gateway installation chosen after checking current IBKR API requirements.
Gateway version, API version, operating system, timezone data, Python lockfiles, model runtime and
code release are bound in each execution release. Version-specific IBKR order and account behavior
must be checked against current official documentation when the plan is implemented; ports and
account-name prefixes alone are not proof of a paper account.

Use immutable release directories and explicit roots, for example:

```
$HOME/trading-engine/releases/<release-id>/   code and dependency lock
$HOME/trading-engine/current -> releases/…   atomically selected release
$HOME/.config/trading-engine/                 non-secret personal-host config
$HOME/.local/share/trading-engine/            single-writer state and private raw data
$HOME/.local/state/trading-engine/            durable runtime logs/outbox
<owner-secret-store>/                        credentials and signing/alert material
```

Package the engine's existing dependency groups as pinned environments; the optional historical
text environment remains separate. Gateway is a separately versioned personal-host component,
not part of the research engine environment. Inventory hard-coded paths, systemd WorkingDirectory,
EnvironmentFile, scheduler UTC/ET assumptions, proxy/model paths, source credentials and recovery
scripts before producing a portable release. Reuse existing installer/recovery machinery where it
passes the rehearsal; do not build a second platform or copy the entire development home directory.

**Hard personal-account rule:** the personal execution host uses only personally owned model
accounts, API keys, proxies, routing configurations and billing. It must never call
organization-managed model endpoints or use organization-managed credentials, accounts, session
tokens, proxies or routing, even if a
copied research release currently works that way. Before first model call inventory the entire
route chain (CLI, proxy, upstream and fallback), replace disallowed bindings with personal ones,
and re-register the resulting identity. A route change cannot inherit the old policy's evidence
unqualified; report deployment identity differences and run the required prospective comparison.
Secret separation alone is insufficient if an endpoint still belongs to an organization.

Config contains account alias, explicit permitted paper account ID reference, client ID, gateway
endpoint, source selections, paths, schedules, registered policy IDs, risk envelope and alert
routing names. Secrets contain broker authentication/session material, model API credentials,
owner signing keys and alert tokens. Store each secret only on its registered personal execution
host or separate personal watcher as required by that role, with restricted file permissions/OS
secret storage; never put them in git, release archives, prompts, crash bundles,
public reports or transfers back to the research host. Logs use opaque account aliases and redact
transport/authentication payloads before publication. A checksum identifies config, not secret bytes.

At startup require all account, environment and endpoint checks to agree, including broker-reported
managed accounts and an explicit paper-account allowlist. A live account, additional unknown
managed account, unexpected margin permission or environment ambiguity denies submission. Bind a
unique client ID to this runtime; another active writer/client for the sleeve blocks activation.
Do not automatically fall back to a different gateway, live account, provider alias or data source.

## Data migration and ongoing synchronization

The personal host becomes authoritative for its broker-paper execution ledger; the research host
continues its frozen research producers unless the owner approves a separate migration. There is
no two-way DuckDB merge and no shared live database file.

1. Produce an existing supported recovery/export bundle under the research writer's coordination.
   If copying a DuckDB file, first quiesce writers, close connections and verify no process holds
   it; copy the consistent database and required checkpoint state together. Never rsync an open
   DuckDB/WAL pair opportunistically. This design session has not opened or copied that database.
2. Manifest code/schema versions, registered cohorts, source receipts, bitemporal facts, simulator
   state, append-only sequence heads, calendar/corporate-action versions and exclusions. Raw
   TradingView transcripts and scraped text retain their private/non-redistributable handling.
3. Transfer over an owner-controlled authenticated encrypted channel, verify bundle checksums and
   restore into a staging root. Validate row counts, sequence heads, expected schema, last completed
   session and a deterministic replay against a saved **synthetic or copied** rehearsal store.
4. Install personal secrets separately. Start collectors/reporters without order authority, run
   one full dry-run exchange session, and exercise backup→restore→startup reconciliation before
   broker-paper activation. Register a new paper cohort; old forward evidence is read-only history.
5. Subsequent sync is immutable, append-only research export batches with availability timestamps
   and cursors, one-way to the personal host if needed. Late exports keep actual arrival time for
   live decisions. Broker execution state never flows back into simulator evidence as invented
   fills. Public summaries may flow back without raw text, account IDs or secrets.

Back up execution state after each terminal order batch and at session close, with encrypted
rolling snapshots and the exact release manifest. A restore target can lose recent local events,
but cannot safely lose broker events: read-only broker reconstruction must recover executions
since the last durable cursor before any order can be admitted. Proposed RTO is 30 minutes to
read-only health; trading has no time-based recovery guarantee and remains halted until reconciled.

## Restart tolerance and runtime sequencing

Reuse the existing one-writer discipline. Persist an attributed intent, reserved risk/cash capacity,
authority consumption and uncertain submission marker atomically before invoking the transport.
Release database write ownership while waiting on broker/model/network responses. Persist broker
acknowledgements and callbacks in short idempotent transactions. The model never holds the writer
or calls the broker directly.

On process restart, Gateway disconnect, client collision or expired session: deny new submissions,
construct a fresh runtime epoch, invalidate prior capabilities, read complete broker state, recover
executions/fees/corrections with overlap from a durable cursor, and reconcile. Stable broker
`permId`, local intent key/orderRef and account ID carry lineage across sessions; transient orderId
alone is insufficient. Execution IDs are deduplicated with correction/bust versions, not replaced
in place. Keep raw/native callback identity privately for adjudication.

If submission succeeds at IBKR but the acknowledgement is lost, the old key stays uncertain until
complete order/execution history identifies it. Finding no order in a partial current-open-order
snapshot does not prove absence: use completed orders and execution history and the existing
resolution semantics. A confirmed absence permanently burns the old key. A replacement needs a
fresh policy-valid intent and fresh risk decision, never an automatic retry of the uncertain call.
Recovery is explicitly two-tier. For a **same-session gap**, query TWS API executions plus open
and completed orders using a durable overlap cursor, reconcile callbacks and IDs, and prove the
history covers the gap. For a longer outage, or whenever the API's confirmed retention no longer
covers the gap, retrieve **Flex Query or official statements** for every missing date plus an
adjacent overlap interval. Import them as append-only broker recovery evidence including trades,
commissions, cash/FX, transfers, dividends, corrections and busts. Link by account/permId/execId/
orderRef and broker statement IDs; mark unmatched items for manual adjudication. Never identify a
trade solely by equal ticker/quantity/price. Flex may lag and its fills may lack some intraday
fields: preserve unavailable timing rather than invent it. Stay halted if statements are not yet
available, any session/sequence cannot be closed, or account totals still disagree. A current
position snapshot alone cannot establish the missing order/fee history.

A cancel acknowledgement racing a fill records both events in arrival order and reconciles the
cumulative quantity; cancellation never implies zero filled quantity.

The future runtime may use an owner-approved daily paper mandate with short renewable capability
windows (proposal: 300 seconds), refreshed only while risk, data, model and reconciliation are
healthy. This is a new execution-plan feature. It must not repurpose the current `execution_authority
=none` design objects or delete halt history. A restart alone may re-establish healthy startup under
that mandate, but a latched loss/mismatch halt always needs owner confirmation before resumption.
No routine per-order owner approval is proposed.

## Exercising IBKR paper in stages

All following actions occur only after the execution plan is approved, on personal hardware.

1. **Offline transport contract.** Implement a versioned IBKR paper adapter against recorded or
   synthetic API messages. Test account validation, contract/conId resolution, unique client
   identity, complete pagination, partial fills, duplicate/out-of-order callbacks, cancelled fills,
   rejection, fee/currency correction, gateway restart and uncertain calls. Every live-account
   mutation remains structurally rejected. No dependency is added under P16 W8.
2. **Read-only connection.** Observe broker server time, managed paper account, account balances,
   positions, open/completed orders and executions. Compare a complete paper account snapshot to
   an independently rebuilt local broker-fill ledger. No submitted order is needed for this phase.
3. **Bounded paper lifecycle rehearsal.** Use a separately registered rehearsal intent with tiny
   paper notional, a liquid admitted instrument and explicit owner mandate. Exercise acknowledgement,
   cancellation, fill/cancel race and expiry. Do not force a fill or silently raise a limit. Synthetic
   drills cover faults that cannot responsibly be manufactured in the paper account. Rehearsal
   observations never enter the strategy's prospective performance cohort.
4. **Opening-order capability test.** P15's limit-on-open fills only at the next opening price plus
   costs and rejects if above its limit. Check IBKR support for the intended listing/route/order
   type and auction time-in-force, cutoff, cancellation and fractional restrictions. Register a
   genuine opening-only limit mapping if supported. A market/DAY order or ordinary limit order
   working all morning is a different execution policy and cannot substitute silently. If native
   support is absent, stop that mapping and propose a separately named execution cohort.
5. **Paired prospective paper cohort.** Feed the identical retained policy decision and deterministic
   target order into a frozen simulator twin and the admitted paper path. Neither borrows the
   other's later fills or prices. Enforce whole/fractional-share decisions, FX/cash sizing and
   broker lot/tick sizes as registered rules, with differences visible. Each target has one local
   key and one broker order lineage; zero unattributed orders is a non-negotiable exit criterion.

A simulator rejected order remains in comparison denominators. Broker-only and simulator-only
fills are legitimate execution differences requiring attribution; they are never deleted to
manufacture matching holdings. An unexpected manual order in the isolated account is an accounting
mismatch and halt until attributed/resolved, not a line to ignore.

## Two distinct reconciliation questions

**Accounting reconciliation** asks whether local knowledge of actual paper activity equals the
broker's authoritative activity. Build a paper mirror solely from confirmed paper executions,
commissions, FX, dividends, corporate actions, transfers, fees, busts and corrections. Reconcile
cash by currency, signed quantities, average costs, outstanding/filled/cancelled quantities and
complete order/execution IDs. Exact normalized monetary units and broker rounding rules are
registered, not a broad dollar tolerance that hides missing events. Unknown monetary scales or
stale marks are unavailable, not matches. Reconciliation snapshot time and completion flags must
cover the same event cut; incomplete/changing snapshots block new orders pending retry.

A proposed cadence is startup, before each opening-order batch, after each terminal batch, every
60 seconds while orders are open, and end of session. Any economic mismatch or unknown completeness
latches a halt and alerts. Delayed commissions can be explicitly pending under known IDs, but cannot
be silently assumed zero; final close reconciliation must include them. Broker report/account
values that cannot be computed from the event ledger remain separately unverified and block the
matching gate when required for risk.

**Simulator comparison** asks how the original mechanical simulation differs from paper. Join by
policy decision and target intent; report eligibility, send/ack latency, limit misses, cancellations,
partial fills, final quantities, fill prices, fees, idle cash/FX and resulting P&L. Known paper versus
simulator fill-price differences are not automatically accounting errors; unexplained broker activity
is. Keep an explicit attribution waterfall: sizing/rounding → order eligibility/limit → filled
quantity → execution price → fees/FX → corporate action → residual. Residual must be zero after
accounting precision rules; differences cannot be waved away as “slippage.”

The existing exact `broker_reconciliation.compare` belongs to the first question when both adapters
represent the same actual paper economics. Do not weaken it merely because the counterfactual
simulator's fills differ. Existing cash/position contracts may need a versioned adapter projection;
retain native fields alongside the projection so omitted balances are auditable.

## Slippage calibration from paper fills

Retain decision, send, acknowledgement and each execution timestamp (UTC), exchange session and
auction phase; native order/exec IDs; conId, side, requested/filled quantity; limit and time-in-force;
reference opening print/arrival bid-ask with source/availability; signed execution price; currency;
commission and fee corrections; and the matched simulator price/profile. Missing or delayed quotes
are explicit and cannot be reconstructed with a later quote.

For side q=+1 buy, −1 sell and quantity-weighted fill P:

```
price_slippage_bp = q * 10,000 * (P / reference_open - 1)
fee_bp = 10,000 * actual_commissions_and_fees_USD / actual_fill_notional_USD
all_in_slippage_bp = price_slippage_bp + fee_bp
sim_error_bp = q * 10,000 * (P / simulator_fill_price - 1)
```

Negative price slippage is improvement and remains negative. Keep opening-auction fills separate
from later executions and use the same reference convention for both sides. Multi-fill orders
aggregate volume-weighted price, sum actual fees once, and preserve per-execution records. Unfilled
orders have no fictitious zero slippage; report fill rate, limit-distance distribution and exposure
shortfall separately. End-to-end policy economics includes the cost of unfilled winners/losers and
latency, not just slippage conditional on filling.

Proposed Stage 2 split: freeze a 40-session measurement cohort before it starts; sessions 1–20
calibrate, 21–40 validate once. Require ≥60 independent filled intents in training and ≥30 in
validation, with ≥10 sessions in each. Per liquidity tier/side cells require ≥20 train / ≥10
validation intents; sparse cells retain the prior model and are explicitly uncalibrated. Do not
manufacture orders to reach counts or extend a cutoff after seeing prices. An insufficient cohort
is reported insufficient; a new future cohort can be proposed. Market-wide dependence is accounted
for with session blocks; partial executions of one intent are not independent samples.

Fit one median signed slippage adjustment per covered tier/side and actual fee schedule separately;
report tail losses at p90/p95, source uncertainty, coverage, and paired errors versus v4/v5 on the
same orders. Future profile fitting cannot mutate the paired simulator running in Stage 2. Proposed
validation screen: median signed pricing residual within ±5 bp and p90 absolute residual ≤25 bp
for covered cells, complete fee attribution and no unexplained execution events. These are proposal
values for owner/lead registration before the cohort, not pre-existing approved thresholds or proof
of live execution realism. If they fail, the report explains failure; no automatic refit on holdout.

W6's OHLCV range/HLC3 statistic tests proxy stability and cannot activate v5. Its independent live
quote and real-VWAP checks describe continuous-session spread/drift, not auction fills. Keep those
diagnostics alongside measured broker-paper executions; do not combine their targets in one fitted
sample or add half-range/half-spread to an auction execution. Any calibrated successor profile is
immutable and applies only to future cohorts, never to already-open positions or the previous
prospective record.

## Loss limits, halts and resumption

`docs/product.md` leaves live limits open: proposed halt at −10% drawdown, −3% daily loss, or any
reconciliation mismatch; resume only on owner confirmation. These are **not approved live limits**.
The execution plan must choose a paper risk rehearsal envelope first and the owner must separately
approve Stage 3. Reuse the frozen policy's stricter constraints wherever applicable: long-only,
unlevered, admitted instruments, deterministic sizing, position/sector caps and entry rules.

Define equity using broker cash plus independently marked positions and accrued known costs in the
registered base currency. External deposits/withdrawals are unitized so they cannot reset high-water
drawdown. Dividends, commissions, FX and trading P&L are performance, not external flows.
Daily return is `(equity_now - equity_previous_session_close - external_net_flow) /
equity_previous_session_close`; unitized drawdown is current per-unit NAV / its running high-water
NAV − 1. Missing/nonpositive opening equity, stale FX/marks or incomplete corporate actions denies
new exposure rather than suppressing a loss. Store the source and cutoff of every mark. Proposed
mark cadence is every 60 seconds while an order or position exists and every five minutes while
flat with no open orders; stale or failed scheduled marks deny new exposure. Freeze the final
cadence in the approved registration.

Proposed deterministic responses to be approved before paper activation:

| Condition | Immediate response | Recovery |
|---|---|---|
| Daily loss ≤−3% or drawdown ≤−10% under selected envelope | Persist halt first; cancel outstanding entry orders; no new exposure | Owner confirms diagnosis, reconciled state and new bounded epoch; no daily automatic reset of drawdown halt |
| Any unexplained reconciliation mismatch, unknown order, uncertain submission/cancel or incomplete history | Persist halt; identify exact outstanding orders, cancel entry orders only where identity is certain; retain existing known risk-reducing sells | Full read-only reconstruction and owner-confirmed resume; no blind flatten against uncertain holdings |
| Gateway/network/model identity or required market-data failure | Stop new exposure; retain intents and alert; don't submit stale catch-up entries | Fresh evidence, complete reconciliation and valid epoch; latched incidents need owner confirmation |
| Personal host unavailable | Remote heartbeat timeout; owner uses broker's independent UI if intervention is required | Recover data and reconcile before authority can return |

An opening order that cannot be cancelled because its registered MOO/LOO cutoff has passed is
**expected exposure**, not evidence that the halt failed. Block every new exposure, retain the
order identity and expected quantity, monitor the auction/fill through the independent broker
surface, and reconcile the resulting fill before any resume or exit action.

Halt and cancel are not equivalent to liquidating positions. The existing emergency-stop code
cancels open orders; it cannot flatten. The owner must choose a risk-reducing exit/flatten policy,
including whether existing sell orders remain active and what happens while disconnected. Never
claim a −3% threshold guarantees losses cannot exceed 3% during gaps, delayed marks or outages.
The recommended paper default cancels only entry orders, preserves existing known risk-reducing
sells, and permits no automatic flatten. `broker_emergency_stop.cancel_all_and_halt` cancels all
open orders, so it cannot implement that recommendation unchanged; add an explicitly versioned
cancel-entry coordinator under the approved execution plan and test sell preservation.
A new flatten plan requires confirmed positions and independently validated reduce-only quantities;
no short position may be created by a duplicate exit. The owner must approve and rehearse the
cancel-entry/keep-sells default before paper activation; automatic flatten is separately blocked
until its reduce-only rehearsal passes. Routine inference cannot change, clear or negotiate halts.

## Concrete owner kill switch

The named operator is the **owner**; register one backup personal operator only if the owner
explicitly appoints them. The owner keeps a personal phone with broker app/2FA and a personal
laptop with the independent broker interface, plus access to the separate personal watcher.
Rehearse both routes before unattended paper trading:

1. **Engine reachable:** from the authenticated personal control surface send `halt_new_exposure`
   with a unique incident ID. The runtime durably latches the halt first, stops capability renewal,
   cancels known open entries and keeps existing risk-reducing sells under the approved policy.
   The acknowledgement reports persisted incident ID, account alias, canceled/pending order IDs
   and positions. If acknowledgement is lost, treat the halt as uncertain and use the broker route.
2. **Engine unreachable:** on the separate watcher's personal control page revoke the short-lived
   execution permit; every exposure-increasing submit/renewal must require an authenticated permit
   bound to account and runtime epoch, with at most 60 seconds of validity. The watcher durably
   records revocation and refuses subsequent permits; a watcher restart cannot clear it. Cached
   permits mean revocation may take up to 60 seconds to stop new exposure, not instantaneously.
   Clock rollback or inability to verify freshness denies exposure. Then use IBKR's independent
   interface on the personal phone/laptop, verify the paper account, cancel outstanding entry
   orders, retain known sells,
   and follow only the approved manual exit policy. The broker route handles orders already in
   flight; permit revocation alone cannot cancel them. Check again after the permit lifetime to
   catch submissions racing revocation, and retain broker confirmations. If connectivity prevents
   confirmation, stay in an unresolved incident and monitor through the broker. Retain the cancel
   as unconfirmed until broker evidence resolves it.
   Before this route is enabled, verify whether the owner's phone login and Gateway can coexist.
   If IBKR permits only one session for the username, the rehearsed order is: latch/revoke local
   authority, stop Gateway auto-relogin, deliberately disconnect Gateway, then sign in through the
   independent paper-account interface. Do not let IBC reclaim the session during intervention;
   reconnect Gateway only into read-only recovery and reconcile before a new epoch.
3. Record operator, UTC time, incident ID, selected account alias, actions and broker confirmation/
   order identifiers in the watcher's durable incident log (or a private dated local note if the
   watcher is unavailable). On engine recovery, import this as an append-only
   `external_operator_halt`/`external_order_action` record with occurrence **and** ingestion times,
   reconcile broker executions/cancellations, and latch the halt before considering new authority.
   Screenshots may support manual adjudication but do not replace execution/statement evidence.
4. Only the owner can confirm resolution and authorize a new bounded epoch after reconciliation.
   Neither a broker-app logout, a host reboot, an alert acknowledgement nor a newly healthy
   heartbeat clears the halt. If the watcher is unreachable, permits expire closed; no automatic
   failover to a second order-sending runtime is allowed.

This future execution-plan surface is a bounded personal control, not a new broker route under
P16. The rehearsal must prove who can act, that the owner's two devices can reach the broker and
watcher independently, and that an offline intervention becomes durable ledger evidence exactly
once when the engine returns.

## On-demand investigation and operations

There is no push alerting. The existing reports and health surfaces retain durable incident state,
and an agent investigates failures on demand. A future personal-host design may keep a local
heartbeat and fail-closed authority state, but it must not add a messaging destination or external
notification dependency without a new owner decision.

Investigate account/environment mismatch, unknown orders, uncertainty, reconciliation breaks,
risk halts, model drift, stale market data/FX, gateway disconnect, disk pressure, broken backups,
and overdue sessions from the retained local evidence. A daily owner digest may report
policy/control results, order attribution, paper/simulator fill differences, risk headroom,
reconciliation status, and the next review date.

The runbook covers startup, reauthentication/2FA, broker maintenance periods, manual incident halt,
backup restore, cancel/fill races, model drift, calendar anomalies, overnight exposure and host loss.
Use the independent broker UI as the operator fallback when the host is unreachable. A report or
investigation is not an order authorization channel and cannot resume trading.
The US open is 21:30 or 22:30 Singapore time as US daylight saving changes. Schedule Gateway
restart and owner reauthentication outside the registered US session, and rehearse an overnight
owner response window that covers both Singapore-time variants.

## Model identity and real capital

Retain exact provider, model revision, toolset, prompt, code, routing configuration, proxy and CLI
runtime identities plus provider request IDs on every decision. The current observable catalogue alias is not a provider-pinned immutable revision. Recommend
extending the product's observable paper-identity policy to this **broker-paper** mandate, with
personal-only accounts/routes, exact observable bindings and drift checks. Record that scope in
the approved plan; a provider immutable revision is not a prerequisite for this recommended paper
experiment. It remains mandatory before Stage 3 real capital. Identity changes mid-cohort mean
unavailable/new epoch or a new cohort, never silent provider fallback.

Before Stage 3 require a provider-issued immutable revision with documented version semantics and
no silent routing to another model. A version-looking alias is insufficient. A request-returned
revision must match registration, and drift denies new model-driven orders. If no provider can
supply it, real capital remains blocked even if paper is flawless. Retain model token counts, but
exclude token credit cost from profitability per product; commissions, spread, slippage, data and
FX costs still count. New model or prompt versions need fresh prospective evidence.

## Acceptance, failure and plan handoff

Propose at least 40 completed exchange sessions within a planned one-to-three-month paper window,
with all 40 observed whether or not an order occurs. Require zero unattributed orders/executions,
zero unresolved economic mismatches at each daily close, no duplicate external submission through
all restart drills, complete operator incident records and measured calibration sample coverage.
A low-turnover policy may not reach fill-calibration counts; this is an insufficient operational
sample, not permission to trade more or claim success from a handful of fills.

The exit report includes paired simulator/paper attribution, all cancellations/rejections and
missing-data denominators, frozen train/holdout calibration, identity history, risk incidents,
restore and remote-alert drills, and unresolved limitations of broker simulation. A single known
fee timing difference may be explained/pending during the day but must reconcile at the required
final snapshot; a missing commission is not a clean session. A failed gate keeps the cohort halted
or in paper review; no automatic live transition or capital scaling follows.

See `execution-layer-plan.proposed.md` for the exact implementation sequence, path ownership,
budget proposal, tests and approval inputs. On copying into the repository, the lead adapts relative
links and assigns the plan number in `docs/plans/README.md`, preserving status **proposed**.

Round-1 review response S1–S7 is mapped in `reviews/round-1-response.md`; the original reviewed
copy is retained as `stage2-broker-paper.v1.md`. All VERIFY items remain implementation prerequisites,
not claims that this session opened an account, installed Gateway or checked a broker entitlement.
