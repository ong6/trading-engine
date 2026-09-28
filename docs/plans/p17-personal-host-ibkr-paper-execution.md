---
plan: P17
title: Personal-host IBKR paper execution and reconciliation
status: proposed
opened: 2026-09-26
owner_decision: select host, account opening/funding and type, commission plan, subscriptions, instruments, currency scope, broker-paper identity, paper risk/exit policy, alert destination and off-host watcher; approve mandate and budget ceilings after a Stage 1 pass
---

## Goal

On the owner's personal host, run one frozen Stage 1-passing policy through a separately registered
IBKR paper execution cohort beside its frozen simulator twin. Attribute every order, reconcile
actual paper economic state and measure paper/simulator execution differences over a registered
40-session window before considering a separate live-capital plan. This plan remains proposed and
authorizes no implementation, account action, broker connection, credential or capital use.

## Why now

P16 W8 prepares this design in advance so a Stage 1 pass need not trigger an improvised deployment.
The current checkout has substantial inert broker-neutral lifecycle/risk evidence, but no IBKR
transport, production authority coordinator or P15-compatible limit-on-open broker contract. P16
itself authorizes none of those additions. The approved product direction is eventual IBKR on
personal hardware, after policy evidence, owner decisions and a separate execution plan.

## Scope

Execute only after owner approval and a Stage 1 prospective pass, with one writer per store.
Read `docs/design/stage2-broker-paper.md`.

1. **Admission and frozen registration.** Record the Stage 1 evidence, chosen account/instruments,
   personal host, account type, commission plan, budget ceilings and risk/mandate/model decisions in
   product/feedback. Register a new paper cohort,
   simulator twin, exact executable release, opening capital/currency, 40 calendar-session dates,
   training/validation split, fees, limits, order mapping and stop criteria before any evidence.
   Resolve every row of the design's Owner decisions table. Recommended defaults are an isolated
   USD sleeve, observable drift-checked personal model identity for broker-paper, and entry-only
   cancellation preserving known sells without automatic flatten. Record each VERIFY prerequisite
   with dated evidence: Singapore cash-paper-account eligibility/funding, ability to leave live
   trade permissions disabled, live data subscriptions, paper Flex/statement availability,
   Gateway restart/2FA and phone-login collision behavior, fees, auction cutoffs/fractions and TWS
   API support. Do not authorize live trading. Proposed artifact:
   `server/ibkr-paper-registration.json`.
2. **Portable release and restore.** Reuse and version existing release-manifest, install and
   recovery tools; locate hard-coded runtime paths before changes. Explicit code/config/state/secret
   roots, locked dependency groups and supported Gateway/API version. Add personal-host deployment
   documentation and a dry-run deployment target; credentials remain local and outside artifacts.
   Audit every model account, key, endpoint, proxy and fallback route: personal ownership only,
   with new registration and prospective identity comparison for changed routes.
   Use a writer-coordinated recovery bundle, verified staging restore and a full dry-run session.
3. **Versioned paper contract.** New `server/ibkr_paper_contract.py` (proposed) preserves
   broker-neutral errors and introduces opening-only limits, native conId/orderRef/permId identity,
   timestamped signed slippage, currency-aware balances and execution/commission corrections.
   Keep current market/DAY consumers and frozen cohorts behaviorally unchanged. Tests document why
   `broker_contract.py` alone cannot represent the required orders.
4. **Transport and read-only startup.** New `server/ibkr_paper_adapter.py` and bounded callback/event
   retention beside `broker_ledger.py`; account/environment allowlist, unique client, complete
   histories and idempotent native-event normalization. Prefer the TWS API to Web API; freeze its
   verified version/capabilities. Reject live accounts structurally. Reconstruct same-session
   gaps using TWS open/completed orders and executions; for older gaps ingest Flex Query or official
   statements with overlap, corrections and fees. Remain halted if any gap cannot be closed.
   Reuse `broker_reconciliation.py`, `broker_startup_readiness.py` and
   `broker_submission_resolution.py` through an explicit versioned projection. Observe paper
   account read-only before any submission surface is enabled.
5. **Risk and authority composition.** New approved production coordinator beside
   `broker_paper_*`; reuse verified lease/intent/usage/runtime/activation/consumption patterns,
   but not test-harness persistence as executable authority. Atomic risk reservation + consumed
   capability + uncertain submission before external call; no DB writer during network waits.
   Restart invalidates old epochs. Deterministic renewals under an owner mandate avoid routine
   per-order approvals; owner alone resumes a latched loss/mismatch halt. Implement approved
   cancel versus risk-reducing-exit response and prove it cannot duplicate an exit into a short.
   Implement a versioned entry-only cancel coordinator; the existing cancel-all helper cannot
   preserve sells. Automatic flatten stays disabled until separately approved reduce-only drills
   pass. Require an authenticated personal watcher permit refreshed within 60 seconds for every
   exposure-increasing submit/renewal, in addition to the bounded local capability. Freeze the
   risk-mark cadence; proposed defaults are 60 seconds with orders/positions and five minutes when
   flat. Orders already beyond the MOO/LOO cancel cutoff remain expected exposure to monitor and
   reconcile rather than being treated as cancelled.
6. **Lifecycle and opening-order rehearsal.** Extend `tests/test_broker_*.py` and add isolated
   IBKR-paper contract/transport tests with synthetic callbacks. Run approved tiny-notional paper
   rehearsal on the personal host, test genuine opening-only limit support, then register the
   execution mapping. Unsupported order semantics are a blocked mapping, never a market/DAY
   substitution. Rehearsal observations stay outside the policy performance cohort.
7. **Paper mirror and simulator attribution.** New paper-account mirror/report module under
   `server/`/`farm/` reuses broker ledgers. Reconcile confirmed executions, cash, fees, currencies,
   corporate actions and unknown/manual orders exactly by canonical accounting units. Separately
   compare simulator intents/fills, limits, quantities and P&L; preserve all failed/unfilled rows.
   No mutation of old simulator fills or P15/P8/P7 policy versions.
8. **Paper-fill measurement and calibration.** New `farm/ibkr_paper_calibration.py` freezes sessions
   1–20 training, 21–40 validation and the sample thresholds in the design. Signed fill slippage
   and actual fees, not OHLCV substitutes; future-only calibrated profile. Publish insufficient
   samples honestly; no forced trades, holdout tuning or retroactive replacement of the twin.
9. **Operations and activation.** Personal-host service units only, disabled until recovery,
   inert-boundary, read-only and paper rehearsal gates pass. Durable alert outbox + independent
   heartbeat watcher + redacted daily digest; fault drills for disconnect, lost acknowledgement,
   duplicate callback, missing history, disk failure, stale model/data, restore and owner resume.
   Rehearse the owner acting from a personal phone/laptop: halt the reachable engine or revoke the
   watcher's permit and cancel known entries through the independent paper broker UI. Import
   offline interventions exactly once as append-only external-operator events when reachable;
   reconcile before owner-only resume. Verify phone/Gateway session collision and rehearse the
   ordered handoff: latch/revoke, disable Gateway auto-relogin, disconnect it, intervene, then
   reconnect read-only and reconcile. Keep restarts and reauthentication outside the 21:30/22:30
   Singapore-time US open, with an owner response window covering both DST variants. Heartbeat
   recovery never clears a latched halt.
   Activate the approved cohort and verify first-cycle lineage before unattended operation.
10. **Verdict.** Freeze the 40-session report, all denominators and incidents, calibrated profile
    identities and independent reviews. Submit the Stage 2 result to the owner. No Stage 3 work
    occurs inside this plan. Any later live-capital plan requires provider-issued immutable model
    revision, capital steps, tax/instrument acceptance and approved loss limits.

## Not in scope

- Broker work, credentials or services on the research host; implementation under P16 W8.
- Company model accounts, keys, credentials, endpoints, session tokens, proxies, fallback routes
  or billing on the personal host. Only personal model accounts and complete personal routing
  chains are permitted; copying a working research configuration does not satisfy this rule.
- Trading real capital, engine connectivity to live-account order endpoints, automatic capital
  scaling or silently lifting halts. Any owner account funding is a separately approved prerequisite.
- New alpha policies, shorting, leverage, derivatives or changing frozen P15/P8/P7 evidence.
- Replacing an unsupported limit-on-open order with an intraday working limit or market order.
- Rebuilding the entire inert broker framework, a new dashboard/platform or a second data lake.
- Treating broker-paper fills as true market fills, or simulated profitability as Stage 1 evidence.

## Done when

Before activation: resolve the Owner decisions table and every required VERIFY item, then pass the
following existing repository commands from its root using its already configured environment.
These are **future implementation gates**, not test results claimed by this design session:

```sh
.venv/bin/python -m pytest -q tests/test_broker_*.py tests/test_simulator_broker_adapter.py tests/test_disabled_live_broker_adapter.py tests/test_release_manifest.py
.venv/bin/python -m pytest -q
TZ=UTC .venv/bin/python -m pytest -q
.venv/bin/python -m tools.metrics_snapshot --check-budget
```

Run the unqualified full suite with the host's actual configured timezone. Existing
`tests/test_broker_boundary_inert.py` must still prove the research host has no enabled broker path;
metrics must stay within approved ceilings. Add these proposed exact commands when the approved
implementation creates the named test files (currently absent; absence is not a pass):

```sh
.venv/bin/python -m pytest -q tests/test_ibkr_paper_contract.py tests/test_ibkr_paper_adapter.py tests/test_ibkr_paper_recovery.py
.venv/bin/python -m pytest -q tests/test_ibkr_paper_cancel_entries.py tests/test_ibkr_paper_kill_switch.py tests/test_ibkr_paper_identity_routes.py
.venv/bin/python -m pytest -q tests/test_ibkr_paper_reconciliation.py tests/test_ibkr_paper_calibration.py
```

The new tests cover live-account rejection, auction semantics, uncertainty/idempotency, fee/bust
corrections, TWS versus Flex/statement gap closure, unknown history staying halted, preserving
existing sells, permit expiry/revocation/replay, external intervention import, personal-only routes
and frozen calibration. If file names change before implementation registration, update these
commands in the approved plan first. The personal-host activation checklist must also fill these
**to be named** command slots with exact invocations and retained output paths before use:

| Command slot | Required evidence | Blocking condition |
|---|---|---|
| `PAPER_READ_ONLY_AND_RESTORE` — to be named | Correct paper account/data entitlements, same-session and multi-day restore with overlap and reconciliation | No missing interval, currency or execution may remain |
| `PAPER_AUCTION_REHEARSAL` — to be named | Registered contract/route, MOO/LOO submit/cancel cutoffs, fractional rejection/rounding, fee plan, duplicate-free lifecycle | Unsupported mapping or simulated fill limitations must be explicit |
| `PAPER_REMOTE_HALT_DRILL` — to be named | Owner phone/laptop actions, independent watcher revocation/expiry, kept sells, offline incident import exactly once, owner-only resume | Unreachable host and watcher failure must deny new exposure |
| `PAPER_FIRST_CYCLE_REPORT` — to be named | New cohort/twin lineage, personal model route binding, fresh model/data checks and alerts | All preceding gates pass before unattended activity |

A placeholder command is incomplete evidence. None of these integration drills is run under P16.

On the personal host: read-only account validation passes, restore reconstructs every event before
authority returns, all acknowledgement/cancel/restart drills produce zero duplicate submissions,
alerts arrive within the registered latency targets, and opening-order semantics are verified for
the registered instruments. The account can be returned to a halted state through the independent
operator channel even when the engine is down.

After the registered window: 40 exchange sessions observed, **zero unattributed orders/executions**,
zero unresolved daily-close economic mismatches, complete twin attribution and a frozen calibration
report. Training needs ≥60 filled intents across ≥10 sessions, validation ≥30 across ≥10; covered
tier/side cells need ≥20/10. If counts or pre-registered error bounds fail, report insufficient/failed
and do not call Stage 2 passed. Independent correctness, methodology and authority/operations
reviews have no unresolved critical issues and score at least 8/10 under the refine loop.

## Budget

Proposal, not a ceiling increase: 12–18 logical implementation commits, each below 1,500 inserted
non-data lines; target ≤2,000 net new server Python lines, ≤500 farm, ≤200 tools and ≤200 simulator
lines, plus focused tests and deployment docs. Prefer replacing duplicated scaffolding over growth.
The owner must approve exact ceilings after the dependency/contract inventory; stop rather than
infer that these targets raise frozen repository budgets.

Allow 3–5 implementation/rehearsal sessions, then 40 exchange sessions of observation within a
planned one-to-three-month paper interval. No spending or subscription is approved by this budget;
account/data/Gateway costs need explicit owner acceptance. Model token cost is excluded from the
profitability verdict as required by product.

## Risks

| Risk | Detection / rollback |
|---|---|
| Paper vs live account ambiguity | Broker-reported account allowlist + environment checks; refuse all mutations |
| Lost acknowledgement or cancel/fill race | Durable uncertainty, native-ID reconciliation, no blind retry; latch halt |
| Snapshot or restored ledger incomplete | Complete-pagination/sequence checks and read-only recovery; no capability |
| Limit-on-open cannot be represented | Capability rehearsal fails; retain simulator-only operation until a new mapping is approved |
| No immutable model revision | Observable drift-checked personal identity is the recommended explicit broker-paper mandate; Stage 3 remains blocked |
| Sparse fills / biased conditional slippage | Full order denominator and fixed dates; insufficient verdict, no forced orders |
| Broker-paper unrealistically optimistic | Report tail/limit/partial-fill limitations; require a later tightly capped live plan |
| Host/alert failure | Independent watcher and broker UI runbook; restore to halted/read-only state |
| Limits breached during a gap | Registered stop/cancel/exit policy and owner intervention; never promise a hard loss bound |

Rollback disables the new paper runtime, preserves ledgers and halts, reconciles any still-open
broker orders through the approved operator procedure, and restores a known release in read-only
mode. It never replays orders from an old backup or clears incident history.
