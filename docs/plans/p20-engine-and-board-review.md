---
plan: P20
title: Engine and paper dashboard correctness review
status: done
opened: 2026-10-05
owner_decision: Owner requested a comprehensive review and improvements with independent reviewers
---

## Goal

Make the existing paper dashboard and reusable engine reliable to operate and inspect, with
reproduced defects fixed, efficient data handling, and complete setup and design documentation.
This is the public infrastructure portion of the owner's 2026-10-05 cross-repository review.

## Scope

- Reproduce and correct generic shared-study input and report defects in `farm/study/`, with
  regression cases in `tests/test_study_*.py`. Review duplicate bars and terminal-zero outcomes
  already recorded in the scope ledger; retain existing valid-input report bytes.
- Review existing dashboard reads and setup in `ui/`, including bounded failure handling and
  dependency/build verification. Add no dashboard pages or API endpoints.
- Diagnose current operational alerts through read-only API and published database snapshots.
  Record the distinction between an actual evidence issue and a broken monitor. Changes to
  frozen registrations, strategy rules, or evidence are excluded. The orchestrator may deploy
  reviewed fixes and restart the existing read-only API and UI to verify them.
- Reconcile `README.md`, `ui/README.md`, the operating runbook and architecture documentation
  where the checked implementation or verified operating state contradicts them.

## How to run this plan

One writer owns this checkout. Alpha and private backups have separate checkout owners.
Reproduce each defect before its fix; run focused tests after the fix and one full suite after
all implementation changes. Then hand the diff and evidence to an independent reviewer and
resolve actionable findings before publication. Keep real data and private research out of
this public repository. The orchestrator owns integration and deployment decisions.

## Not in scope

New alpha, retuning, backfilling or editing frozen evidence, P7/P16 activation, broker integration,
real capital, data purchases, and restarting or mutating live producers. Existing plans remain
under their own admission rules. No external model CLI is used for this review.

## Done when

The reproduced defects have passing regressions; `.venv/bin/python -m pytest -q -W error -n auto`
passes (or platform-specific limitations are reproduced independently and reported);
`.venv/bin/ruff check .`, `cd ui && npm test && npm run build` and the metrics budget pass.
The read-only host audit is documented with accurate remaining actions, and a fresh reviewer
has checked the implementation and its scope.

## Budget and risks

At most five logical implementation/documentation commits, each below 1,500 inserted lines.
No new operator CLI, endpoint, or monitoring service. Rejecting formerly accepted duplicate
input is intentional; preserve results for valid input and do not rewrite stored research.
UI request cancellation must preserve caller cancellation and never retry a mutation.

## Verified outcome — 2026-10-05

The bounded review is complete. Independent review found no remaining blockers after the
generic input/report and forward-projection fixes. The complete Linux suite passed 4,309
cases; 54 UI tests, production compilation and browser checks at 390px and 1280px also passed.
[CI on the implementation](https://github.com/ong6/trading-engine/actions/runs/37283503856)
passed both UTC and Asia/Singapore suites, dependency audits, packaging and the UI build.
After deployment the live API reports the unchanged two-session XS evidence as accumulating,
and all four dashboard routes load without JavaScript errors. The mobile status region stays
inside the viewport and supports keyboard scrolling. Real source-quality warnings remain
visible; existing evidence and frozen contracts were not rewritten.
