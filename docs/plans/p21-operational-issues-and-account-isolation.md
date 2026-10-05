---
plan: P21
title: Operational issue closure and separate paper accounts
status: active
opened: 2026-10-05
owner_decision: approved by the owner's request to fix every issue from P20 and retain separate strategy accounts
---

## Goal

Resolve the actionable operational defects identified by P20, retain enough source evidence
for honest investigation, and prove that many strategies can run with independent paper
holdings, orders, fills, cash and equity. Improve the 32 advisory server/tools complexity
findings without changing established behavior or hiding registered source changes.

## Why now

The owner explicitly requested all remaining issues be fixed, using separate implementation
and review agents, and clarified that each alpha account must have its own saved state.
P20 found truncated verifier evidence, historical queue failures without a resolution audit,
a provider rejecting a maximum-history request, stopped resumable capture, and stale
walk-forward source identity. These are operational findings, not evidence of profitable alpha.

## Scope

- `engine/verify_prices.py` and generic helpers: retain complete verification identities,
  discrepancies and source bytes; reject invalid symbols/numbers/ambiguous comparison basis.
- `engine/collect.py`: full-history request fallback only when full coverage is established.
- `engine/queue_runner.py`, `server/queue_monitor.py`: explicit append-only cancellation and
  resolution records that preserve original failed jobs and require evidence.
- `tools/free_massive_minute.py`: bounded retries and resume for transient transport failures,
  preserving request pacing, rolling window and immutable manifests.
- Existing walk-forward operation: create a current source cohort without rewriting old results.
- Existing paper-account schemas and simulator: prove isolation of holdings, orders, fills,
  cash and equity by portfolio identity, and fix any demonstrated cross-account leakage.
- Behavior-preserving extraction for the 32 `ruff --select C90 server tools` findings; maintain
  the existing threshold of ten. A changed registered file must use the existing registration
  revision/rehearsal mechanics before deployment; never change a gate to hide the hash change.
- Targeted tests, design/operations documentation, independent review and supported-host checks.

## Not in scope

No private strategy definitions/results, new strategy activation, model-policy calls, Trae,
broker connection, money, data purchase, new schedule, retroactive fill, frozen rule tuning,
or change to retained evidence. Missing external corporate-action evidence stays unresolved
until verified. Historical source bytes and registration revisions remain reproducible.

## How to run this plan

Run end to end under the owner's authorization. One writer owns each checkout; independent
review agents use read-only inspections or isolated worktrees. Reconcile published host work
before publication. Record each reproduction before its fix, commit each logical change below
1,500 inserted non-data lines, then run focused checks and one complete supported-Linux suite.
The orchestrator owns technical choices and deployment after independent acceptance.

## Done when

All reproduced fixes pass targeted regressions; account isolation is demonstrated under
multiple strategies; required Python/UI checks and metrics budgets pass. Advisory complexity
has no unreviewed finding. Changed registered producer identities are rehearsed through the
existing revision path before use. Independent reviewers find no unresolved blocker. Live
checks establish actual progress while genuine unavailable-source gaps remain explicitly named.

## Budget and risks

At most 18 logical commits, each below 1,500 insertions, and 4,500 added test/documentation lines.
No per-layer ceiling is introduced. Exact source identities couple operational improvements to
registration: preserve original modules/revisions until their replacement is properly bound.
An abbreviated provider result never counts as complete history. A newer successful queue job
never clears an older failure without evidence of the same work.
