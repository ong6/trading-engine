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
- `engine/history_recovery.py`: explicit full-history maintenance only when complete listing
  coverage, current security identity and every overlapping stored bar agree. The collector
  stays byte-identical to the frozen forward contract; no wrapper, monkeypatch or new schedule.
- `engine/queue_runner.py`, `server/queue_monitor.py`: explicit append-only cancellation and
  resolution records that preserve original failed jobs and require evidence.
- `tools/free_massive_minute.py`: bounded retries and resume for transient transport failures,
  preserving request pacing, rolling window and immutable manifests.
- Existing walk-forward operation: create a current source cohort without rewriting old results.
- `engine/paper_accounts.py`: generic immutable account-spec and timely intent intake over existing
  engine-owned portfolios. Private alpha owns generation/specification; engine owns balances,
  positions, fills and equity. New accounts use separately funded USD 10k/50k/100k tiers selected
  by private feasibility planning; options/futures refuse until their execution models exist.
- Existing paper-account schemas and simulator: prove isolation of holdings, orders, fills,
  cash and equity by portfolio identity, and fix any demonstrated cross-account leakage.
- Behavior-preserving extraction for the 32 `ruff --select C90 server tools` findings; maintain
  the existing threshold of ten. A changed registered file must use the existing registration
  revision/rehearsal mechanics before deployment; never change a gate to hide the hash change.
- `tools/backup_database.py`: admit complete `data/_meta.json` up to the existing 8 MiB
  snapshot contract during both secure copying and bundle verification. Preserve the 1 MiB
  limit for other artifacts. This registered correction requires revision 12 and rehearsal;
  retain all 135 dependency paths and unchanged policies, books, clocks, gates and schedules.
- Targeted tests, design/operations documentation, independent review and supported-host checks.
- Supported-host review corrections: optional TradingView cross-check errors degrade to missing
  evidence; backup verification fingerprints its opened directory rather than a procfs descriptor
  symlink. These are reproduced operational defects, not new runtime authority.

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

At most 21 logical commits, each below 1,500 insertions, and 4,500 added test/documentation lines.
No per-layer ceiling is introduced. Exact source identities couple operational improvements to
registration: preserve original modules/revisions until their replacement is properly bound.
An abbreviated provider result never counts as complete history. A newer successful queue job
never clears an older failure without evidence of the same work.


## Acceptance correction budget

Full-metadata integration acceptance exposed three defects: the aggregate board metadata
exceeded the generic file cap, the monitor still required a truncated disagreement list, and
the recovery-bundle metadata reader retained the same one-MiB cap. The first two corrections
are outside registered/runtime source closure. The backup correction uses the admitted P15
revision and rehearsal path; it does not change the research runtime identity or trading rules.
The orchestrator extended the execution budget from 18 to 20, then 21 logical commits. The
existing source-commit assertion requires the reviewed source correction in commit 20 followed
by its exact source identity, revision 12 and closure in commit 21. Publishing those commits
together retains the assertion without a self-referential commit hash or weakened gate. The
1,500-insertion per-commit limit and 4,500 added test/documentation-line budget are unchanged.
