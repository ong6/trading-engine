---
plan: P7
title: Autonomous three-mode paper trial
status: active
opened: 2026-09-20
owner_decision: approved 2026-09-20
---

## Goal

Run a capital-disabled, fully autonomous paper comparison on one Linux box using an owner capital
envelope of **S$10,000**. Three isolated counterfactual books receive the same admitted facts,
signal dates, execution model, risk envelope, and frozen USD-equivalent opening balance:

1. **Algorithm-only control:** the registered deterministic dual-momentum rule.
2. **AI-only:** a model chooses one of SPY, EFA, BIL, or cash at the registered monthly boundary.
3. **Algorithm + AI:** the same deterministic order candidate, with AI allowed only to veto an
   eligible buy; it cannot invent an order, change the symbol, side, quantity, or risk limit.

“Fully autonomous” means no routine human approval per paper decision. Deterministic code—not the
model—continues to own data admission, risk limits, sizing, idempotency, next-open fills, accounting,
reconciliation, halts, and immutable attribution. No broker connection or real capital is included.

## Capital and currency contract

- S$10,000 is the eventual owner capital envelope and the notional starting size of **each**
  counterfactual paper book. Three cloned books do not represent S$30,000 of deployable capital.
- At activation, record one independently sourced SGD/USD observation, its timestamp, raw evidence
  identity, and the exact resulting USD opening balance. Freeze that balance across all arms.
- Primary comparison is in USD so FX movement cannot masquerade as a decision-policy difference.
  A secondary SGD translation may be reported only from retained, independently identified FX
  observations and must never change the books' USD accounting.
- This capital envelope is **not** a Sharadar/Norgate subscription budget. P3 purchase authority
  remains blocked until the owner separately approves an initial and recurring data spend.

## Current readiness — 2026-09-20

| Area | Rating | Evidence and gap | Activation target |
|---|---:|---|---:|
| Deterministic safety boundary | 9/10 | No broker route or authority; validation, risk, idempotency, next-open fills, and fault drills exist | 9/10 |
| Decision provenance and logging | 8/10 | Append-only attempts/events retain context, request/response identity, terminal result, and token usage | 9/10 |
| Scheduler and service continuity | 8/10 | Agent data/shadow timers are enabled; last services succeeded | 9/10 |
| Shared-data comparability | 8/10 | A hash-bound three-arm manifest now exists; shared content evidence, cohort identity, and FX remain blocked | 9/10 |
| Model reproducibility | 4/10 | Current model uses an unversioned alias with no provider revision | 8/10 |
| Trial automation | 3/10 | Agent-only shadow is scheduled; hybrid is manual and no tri-arm orchestrator exists | 9/10 |
| Isolated return attribution | 2/10 | Reserved AI/hybrid portfolios and return series do not exist in the live store | 9/10 |
| Unified operator observability | 7/10 | One read-only status now names all activation blockers; paired windows and arm performance await runtime evidence | 9/10 |
| Strategy evidence | 3/10 | One legacy model no-action and cadence-only registered attempts cannot compare policies | Time-gated |

The current system is safe enough to extend but **not ready to activate this trial**. Safety ratings
do not substitute for evidence that any arm has an edge.

## Frozen experimental contract

- Use the same SPY/EFA/BIL/cash universe and the same monthly decision boundary for all arms.
- All arms start on the same future market date after activation gates pass. No retrospective
  decisions, backfills, retries with a different model, or cherry-picked start date.
- Use `baseline_v1`, next-session-open fills, identical costs/slippage, long-only positions, no
  leverage, no shorting, no options, no margin, and gross exposure at or below opening capital.
- AI-only may emit cash/no-action or one target asset. Its order is deterministically derived and
  capped; the model cannot submit quantity, bypass risk, or mutate the portfolio directly.
- Hybrid v1 remains veto-only. A more creative overlay is a different policy and requires a new
  preregistered plan after this trial; it cannot be introduced mid-cohort.
- AI-only model/role/prompt/toolset/catalog identities are frozen. A model alias or provider
  revision that cannot be made stable blocks activation; later identity drift halts the affected
  arm and starts no replacement cohort without an explicit review.
- AI-only transport or malformed-output failure becomes cash/no action. Hybrid failure preserves
  the unmodified deterministic signal. Neither outcome is regenerated for that window.

## Required logs and observability

Every decision window must join, by immutable identities:

- trial, cohort, arm, policy, model, prompt, toolset, source, snapshot, FX, and execution profile;
- scheduled time, actual start/end, latency, response ID, token usage, and terminal outcome;
- complete admitted context, AI decision or deterministic candidate, validation gates and reasons;
- derived order, next-open fill or rejection, costs, positions, cash, equity, and control returns;
- idempotency/replay status, scheduler/service state, fault-drill identity, and any halt reason.

Add one bounded read-only trial status projection and one UI panel rather than another collection of
operator surfaces. It must show freshness and completeness for each arm, paired-window coverage,
unattributed/cross-book rows, model/data/config drift, missing fills/equity, reconciliation status,
decision outcomes, exposure, turnover, costs, return, drawdown, latency, and token consumption.
Raw prompts, responses, credentials, and market values remain protected by existing bounded views.

The following halt the AI and hybrid mutation paths before another decision: stale or incomplete
facts, model/prompt/toolset drift, a missing terminal event, duplicate/conflicting window,
unattributed order/fill, cross-book contamination, reconciliation mismatch, stale equity, failed
fault drill, scheduler gap, or an unhealthy local model transport. Missed windows are recorded and
excluded from paired performance; they are never recreated after observing later prices.

## Scope and implementation order

1. **Trial manifest and status first.** Add a versioned, hash-bound trial registration and a
   read-only status projection over existing ledgers. Prove it reports every current blocker.
   **Completed 2026-09-20:** the manifest freezes the three arms and non-authorizing contracts;
   `GET /paper-trial/status` reports 13 fail-closed blockers. Forged hashes, dummy books, and
   legacy P5 US$39k artifacts cannot satisfy semantic gates.
2. **Stable model and fair AI contract.** Replace the single-ticker proposal shape with a new
   versioned SPY/EFA/BIL/cash target-choice policy while preserving the old evidence. Pin a stable
   model revision or remain blocked.
3. **Isolated books.** Use the existing backup-gated migrations/preflight to create inactive AI
   and hybrid portfolios at the same frozen USD equivalent as a new algorithm control clone.
4. **One simulator-only orchestrator.** On each monthly boundary, snapshot once, derive all three
   decisions, validate, persist attribution, and write only simulator orders. Partial publication
   halts the cohort. No broker adapter is reachable.
5. **Operations.** Add the one timer/postflight path, the unified UI panel, alerts through the
   existing local operational mechanism, and trial-specific fault drills. Activate only after a
   clean backup/restore rehearsal and independent review of boundaries and attribution.
6. **Observe.** Run unattended for at least 90 calendar days and 60 completed market sessions,
   with at least three paired monthly decision windows. This is an operational pilot, not enough
   to declare a winning strategy. Require at least 12 paired monthly windows before a comparative
   policy verdict; report confidence intervals and all missing/failed windows.

## Activation gates

- One complete dry-run signal window for every arm, with exact replay and zero extra model calls.
- Stable model revision available; no `unversioned-catalog-alias` in the active trial manifest.
- Three inactive isolated books reconcile from the same opening balance and date.
- Unified status is `ready`, fault drills are current, backup/restore rehearsal passes, and the
  full Python/UI/static suite and metrics budget are green.
- No broker route, credentials, live toggle, external order submission, or real-capital path.

## Stop and promotion rules

Stop and retain evidence on any capital/risk breach, ledger integrity failure, unexplained
reconciliation difference, model identity drift, or two missed paired decision windows. Operational
failures are not converted into hypothetical trades. Performance does not permit tuning during the
cohort.

After the 90-day pilot, continue unchanged or close the failed arm. No real-capital promotion is
automatic. Any IBKR paper connection is a separately approved later plan, and live capital needs a
new explicit owner decision after evidence review.

## Not in scope

- Sharadar/Norgate purchase, ingestion, or credentials.
- IBKR/Moomoo gateway installation, account access, market-data subscription, or API calls.
- Live orders, real capital, human discretionary overrides, new strategy families, grids, or
  tuning the three policies after seeing results.
- Reusing the three cloned paper balances as evidence of S$30,000 deployable capacity.

## Done when

- The trial ran for at least 90 calendar days and 60 completed sessions with at least three paired
  windows, zero unexplained accounting differences, zero unattributed orders/fills, and no safety
  breach.
- Every expected window is terminal or explicitly missing with a non-backfilled reason; status and
  UI agree with the append-only ledgers.
- A frozen report compares all three arms against the same control, costs, and dates without making
  a superiority claim before 12 paired monthly windows.

## Budget

At most eight implementation commits across six sessions. New non-test code is capped at 1,200
`server/` lines, 300 `tools/` lines, and 200 `sim/` lines; reuse and deletion are preferred. Each
commit remains under the repository-wide 1,500-line insertion limit and completes one numbered
scope item.

## Risks

The main scientific risk is mistaking a short operational pilot for strategy evidence. The main
engineering risks are unversioned model drift, cross-book contamination, partial decision-window
publication, and silent scheduler failure. The frozen cohort, paired-window status, deterministic
risk boundary, append-only attribution, and fail-closed halts address those risks without granting
broker authority.
