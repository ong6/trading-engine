---
plan: P25
title: Ship continuously, clean the docs and code, keep the engine easy to extend
status: active
opened: 2026-11-23
owner_decision: approved by the owner's 2026-11-23 instruction to deploy merged work, clean up code and docs, shorten local backup history and freeze the UI
---

## Goal

A change merged to `main` with green CI reaches the host by itself, safely, without a live agent
session. The docs state current truth only and let an agent find what it needs progressively.
Dead code, stale branches, finished lane clones and old local backups are gone. Adding a
strategy or experiment has one short documented path.

## Why now

Merged work stops reaching the host whenever the orchestrator session ends: batch B (snapshot
lock and API latency fixes) sat unmerged for days. The P15 registration pins about 175 files, so
most code changes need a registration revision, migrations and a rehearsal, and fixes pile up
into batches. The docs restate dated status and old incident rules, so agents read stale facts.

## Scope

1. **Ship batch B as registration revision 25**: `r25/snapshot-lock`, `r25/api-latency`, the
   EBADF-safe unlock and bounded wait on `.generation-publish.lock`, the smallest fix to
   `tools/release_deploy.py`'s runtime check and the UI busy-body match, and the EMBJ ex-date
   rule in `engine/actions.py`, under one re-pin.
2. **Continuous deploy**: a timer-driven deployer (`tools/auto_deploy.py`) that takes the newest
   `main` commit with green CI, runs `tools/deploy_gate.py`, fast-forwards the live checkout,
   applies changed units and restarts the API/UI only when their code changed
   (`tools/install_automation --apply`), post-checks, rolls back automatically on failure, acts
   only inside the safe windows and records each run where the hourly digest reads it.
3. **Mechanical re-pin**: a tool that writes the next registration revision for pinned-file
   changes that alter no registered value, plus a digest-only rehearsal of the E1, sector and
   XS migrations. The pinned set may shrink to the files that can change P15 evidence, with the
   proof recorded in the P15 plan.
4. **No live-session dependency**: the merge and deploy path is a documented command any session
   or the timer can run to completion.
5. **Docs**: root `AGENTS.md` as a short map; a short README per top-level directory; `docs/`
   organised by task; dated material (BUILDLOG archive, audits, finished plans, the feedback
   ledger) under `docs/history/`; doc-pinning tests updated to the new structure.
6. **Backups**: `trading-data` on GitHub is the backup of record; local deploy and rollback copies
   are pruned after a verified deploy, keeping the last two; lane clones are removed once their
   branch is merged and pushed.
7. **Cleanup**: one-shot migration tools that have run, code for retired books and plans, stale
   remote branches, Dependabot PRs, tracked build output, clean lane clones, temporary files.
8. **Extension path**: one short doc for adding a strategy or experiment (infrastructure here,
   registration in the private alpha repo).

## Not in scope

New UI work or mobile support (the UI is frozen: it keeps building and passing its tests). Any
change to a registered value, kill criterion, pass bar, label rule, fetch limit or frozen
statistic. Weakening the deploy gate, pre-registration or the registration identity check.
Disturbing running producers or the E1, sector and XS forward records.

## Done when

- Revision 25 is deployed, with a BUILDLOG entry, and `GET /meta` reports it.
- `tools/auto_deploy.py` has run in dry-run through at least one full nightly cycle with correct
  decisions, then runs unattended; a merge to `main` reaches the host with no session open.
- `python -m tools.registration_identity` passes on `main` and the re-pin tool reproduces the
  revision-25 pin byte for byte.
- Root `AGENTS.md` is under about 80 lines and every top-level directory has a short README;
  no doc on the read path carries a dated status block or an attributed quote.
- Local backups and lane clones follow the retention rules; stale remote branches are gone.
- The full suite passes under `TZ=UTC` and `TZ=Asia/Singapore` on the final `main`.

## How to run this plan

The orchestrator runs the scope items in order. Workers (sub-agents or Codex sessions) each get
one clone under `~/engine-lanes/` and one branch; at most three write at once. The orchestrator
reviews every branch, merges to `main`, re-pins once per batch and deploys outside 14:05–14:35
and 22:30–03:00 UTC. Once the deployer is live, merging to `main` is the deploy.

## Budget

Hygiene budgets in `AGENTS.md` apply per commit. Registered-file changes are collected into one
re-pin per batch.

## Risks

A bad automatic deploy: the deployer runs the gate first, keeps the previous commit and unit
state, and rolls back on a failed post-check. A pinned-set reduction that hides an evidence
change: excluded files need a written proof, and the identity check still covers the rest.
