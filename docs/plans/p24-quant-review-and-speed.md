---
plan: P24
title: Senior-quant review, pipeline fixes, speed and new research lanes
status: active
opened: 2026-10-21
owner_decision: approved by the owner's 2026-10-21 instruction (docs/feedback.md) to review and fix the pipelines, make everything faster, and send agents to find new strategies, with authority to fix whatever needs fixing and push
---

## Goal

The engine runs correctly and faster, the accepted wave-1 work lands, and the alpha programme
has a fresh, ranked pipeline of candidates with several new pre-registered studies through
shakedown or development. Correctness over speed: no speed change ships unless its outputs are
identical to the old path on a recorded fixture or store copy.

## Why now

The revision-15 release is on main and the accepted wave-1 and revision-16 lanes are waiting to
land. The proposed-not-approved invariant defects in `scope.md` have no fix branch. The full suite
takes minutes per run, twice in CI. The research programme has killed every price-only idea, and
its only live candidate (trial 287) depends on unconfirmed auction fills.

## Scope

Lanes run in parallel, each in its own clone and branch (`p24/<lane>` in this repo,
`study/<lane>` in the alpha repo). The orchestrator is the only writer of `main` in both repos.

| Lane | Repo | Work |
|---|---|---|
| ops | engine | 7-day producer and stage audit from the journal and logs; fix every failing or silently-skipping producer; revision-15 install status |
| integrity | engine | the 2026-10-20 snapshot-invariant defects (stale provisional opens, WLFC third basis, NaN walk-forward JSON) and the verifier stdout dump |
| nightly-speed | engine | per-stage wall-clock profile of the nightly and weekly drivers; speed up the slowest stages with identical outputs |
| sim-speed | engine | profile and speed up replay, fills, walk-forward, evaluation statistics and the shared study panel used by research evaluators |
| test-speed | engine | cut full-suite wall-clock without dropping coverage |
| quant-audit | engine + alpha (read) | audit DSR/PSR, bootstrap, IC, costs, next-open fills, survivorship and look-ahead; reproduce and fix defects |
| integrate | engine | land the accepted wave-1 lanes; prepare revision 16 with a store-copy rehearsal |
| literature | alpha | ranked sweep of published anomalies that survive costs and fit our data and constraints |
| sec-text, micro, xasset, momentum | alpha | one pre-registered study each, through registration, evaluator, shakedown and, after orchestrator "go", development |

Trial numbers: sec-text 323-332, micro 333-342, xasset 343-352, momentum 353-364. Concurrent
studies use census N=364 for DSR. The committee study keeps 318-322.

## Not in scope

Broker code, credentials or real capital; data purchases; opening any sealed holdout without an
orchestrator decision recorded in the alpha repo; tuning a registered value after its outcome;
editing the live checkout, the live store or running units outside a merge to `main`.

## Done when

Every lane has merged or recorded a verdict; the full suite passes under `TZ=UTC` and
`TZ=Asia/Singapore` on the merged `main`; each speed claim has a before/after timing and an
identity check in its BUILDLOG entry; each study has a registration, evaluator, shakedown and a
recorded verdict or checkpoint.

## Budget

Registered-file changes are collected into one registration re-pin by the orchestrator.
Hygiene budgets in `AGENTS.md` still apply per commit.

## Risks

`main` is what the nightly runs, so a bad merge breaks producers that night: every merge needs
both timezone suites green first. Speed changes can shift outputs silently: identity checks are
mandatory. Many lanes share 32 cores with the producers: heavy jobs run niced with bounded
workers.

## How to run this plan

The orchestrator spawns one agent per lane, reviews each branch, merges serially to `main` after
both timezone suites pass, and does the single re-pin. Lanes never push `main`.

## Progress

- 2026-10-21: merge batch 1 (`p24/integrity`, `p24/quant-audit`, `p24/ops`, `p24/test-speed`)
  issued as registration revision 16. The storage work then numbered 16 was renumbered.
- 2026-10-22: merge batch 2 (`p24/ops-2`, `p24/sec-time`, `p24/nightly-speed`, `p24/sim-speed`)
  issued as registration revision 17; P18 core `p18-study-v3`. Wave 1 (public-hygiene gate, lane
  tool, release tool dry-run, audit-only job registry, dataset catalogue, StudySpec runner and
  research cache) landed on `main` at `483564b6`. The live store repair corrected 18,798 rows.
  Full suites: 5,848 passed under `TZ=UTC` and `TZ=Asia/Singapore`.
- 2026-10-22 (later): registration revision 18 moves per-ticker detail out of `data/_meta.json`
  (3.9 MB to about 31 KB on that day's data); revision 19 charges backtest and walk-forward fold
  books the live books' dollar fees from the 2026-10-19 cost break; the CI hygiene gate stops
  refusing data pushes; `engine.repair_integrity --names` restated MNST's missed 2:1 split on the
  live store (10,243 rows, originals kept in `price_observation_rejects`).
- Checkpoint, storage revision (now numbered 21): held, not deployed. Migration 0000 now applies
  to the deployed catalog on a real store copy, but a fresh review rejected the branch: producer
  read-only opens were redirected to published generations (the nightly would stop advancing
  books), reads refused between publications, the deploy checklist's lock order and rollback were
  unsafe, and new writers wrote a payload encoding the previous code cannot read. The fixes and a
  rehearsal that includes one real nightly, a queue drain and a weekend are in progress; deploy
  waits for a passing re-review and, independently, for a private consumer of the published
  snapshot path to move to generations (not before 2026-11-03).
- 2026-10-22 to 10-23: reliability-ops landed (timer audit, finite minute-capture unit, local
  schedule-contract overlay, status endpoints 45 s to 3 s and 7 s to 2 s); the CI/CD lane landed
  (content-only paths filter, PR fast tier, affected-test selection, `ci` gate, slow markers, 25 s
  duration budget on main); main CI is green again (first since 2026-10-20) after the ci-green
  rounds fixed dependency advisories, two lint steps, the research sandbox on shared-library
  interpreters and a shared-setup charge in the duration budget.
- Checkpoint, storage revision 20: reviewed in four rounds and ready on `p24/storage-r18`
  (`f0282839`); deploy and rollback scripts rehearsed on mirrored-live sandboxes, including one real
  nightly and byte-identical restores. Deploy is scheduled after the private trial's first epoch
  (2026-11-03 06:30 UTC), in one sitting with that consumer's switch to generations, outside
  22:15-23:59 UTC, after fresh suites on the merge commit and a fresh re-pin check.
- Open: the deploy above; incremental capture (copy only changed table data) as a follow-up to cut
  publication I/O. The alpha study lanes report in the private repository.
