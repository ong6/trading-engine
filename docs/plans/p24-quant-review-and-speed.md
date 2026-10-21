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
