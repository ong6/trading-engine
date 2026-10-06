---
plan: P21
title: Operational issue closure and separate paper accounts
status: done
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


## Verified implementation and public refresh — 2026-10-05–06

The earlier supported-Linux suite passed all 4,381 tests at `184a127`. Earlier implementation
[CI at `26a4831`](https://github.com/ong6/trading-engine/actions/runs/37344692854)
passed both UTC and Asia/Singapore suites and the UI build. Independent account-boundary
review passed ten engine and nine private-alpha checks; all 32 advisory complexity findings
were removed at the unchanged threshold of ten.

The generic [paper-account contract](../paper-account-contract.md) is implemented. Private
alpha owns generation, versioned trade specifications and manual/all/auto capital-tier planning;
the engine owns independently funded USD 10k/50k/100k accounts, holdings, orders, fills, cash
and equity. Account creation is idempotent and starts inactive. Tier selection and feasibility
do not activate a strategy. Stock/ETF requests use existing next-open execution; options and
futures remain research-only and are explicitly refused by engine admission.

The isolated walk-forward refresh completed all 18 registered public demo books on 2026-10-05.
Their source identity remains `e533fb3b2cbb71a883fdb88ff4af0b6257676575c4e7bc0bfb80df4cf0373c4e`.
The refresh retains the frozen protocol. The public refresh was published at `ed51c0f`.
Its monthly-report publication projection changes only a source label and stale introductory
wording; it preserves the completed result JSON, statistics and configurations exactly.
Original output and independent acceptance are preserved privately.
This is current research evidence, not a profitability or strategy-activation verdict.

Revision 12 binds the reviewed recovery-metadata limit correction through the existing source
amendment and rehearsal path. The 135 dependency paths are unchanged; only the backup helper's
source binding changes from revision 11. Registered policy values, activation clock, books,
labels, gates and schedules are unchanged. The research runtime identity above and the frozen
XS collector remain byte-identical; no strategy, broker or derivative authority was introduced.
The revision-12 fixture rehearsal passed 165 cases, and independent Linux backup/metadata/JSON
acceptance passed 190 checks. The full Linux run exercised 4,403 tests: 4,402 passed and one
failed because the isolated checkout lacked its conventional `.venv/bin/python` path. After
adding that scratch-only path to the same interpreter, all six tests in the affected module
passed; no source change was required. This is a complete run plus an environment recheck,
not a single all-green run. The earlier CI result above is historical; final revision-12 CI
is recorded separately.

## Recovery acceptance and closure

The final private capture, fresh database restore, independent archive download and private
publication were verified before closure. An earlier daily backup used the existing locked-copy
fallback when the complete metadata exceeded the old cap. The retained daily checkpoint passed
separate database restore and exact committed-file checks; its actual method and commit are
recorded in the private receipt. This alone does not prove the corrected large-metadata bundle
path ran on the host. Checks include the original price receipt, walk-forward
preservation and final acceptance evidence. Detailed manifests, exclusions and execution
receipts remain private. These checks cover the identified captures and files, not later arrivals.
The separately fetched daily checkpoint matched all 326 retained files (27,174,391 bytes).
Its engine export restored 91 tables / 62,668,968 rows; the two registered research exports
restored 2 tables / 400 rows and 2 tables / 69,184 rows. The remote commit matched before
and after the drill. Full checkpoint identities and command receipts remain private.
P21 is complete; P15 continues collecting under its unchanged registered authority.
