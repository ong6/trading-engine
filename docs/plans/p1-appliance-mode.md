---
plan: P1
title: Appliance mode
status: active
opened: 2026-09-18
owner_decision: none
---

## Goal

The engine runs unattended as an evidence appliance and the agent loop shrinks to a weekly
check. Four consecutive weeks pass in which the frozen layers do not grow, no session exceeds
its budget, and every scheduled producer publishes on time. The documentation an agent must
read to operate the box fits in five files.

## Why now

The 2026-09-18 review (see `../feedback.md`): 46k lines of `server/` for a paper broker, a
61k-line commit, 741-line BUILDLOG entries, and research gates that cannot fire before 2027.
Every additional build session costs tokens and adds read cost for the next session while
moving no research counter.

## Scope

1. **Session cadence.** Replace the daily build loop with one weekly agent session (suggest
   Monday, after the Sunday walk-forward) whose whole job is the `AGENTS.md` session shape:
   read, snapshot, check producers, fix a reproduced defect if one exists, publish, stop.
   Where the loop is driven from the store's build mission, that mission is already updated
   to point here.
2. **Retire documentation-pinning tests.** `tests/test_docs.py`,
   `tests/test_docs_architecture.py`, `tests/test_docs_research_evidence.py` pin prose to
   code with ~150 assertions. Keep only: the link checker, the BUILDLOG tail-marker test, the
   "every doc is indexed" test, and any test that compares a doc to a runtime constant
   (schedules, risk names, caps). Delete the rest. This is the one deletion this plan admits,
   and it unblocks the two items under "Proposed, not approved" in `../scope.md`.
3. **Doc diet, after item 2.** Split `../how-it-works.md` into `ops-runbook.md` (the
   "checking on it" and "viewing the UI" sections, target under 400 lines) and
   `architecture.md` (the rest, unchanged text, just moved). Move every dated audit and review
   into `history/` and index them from one line each in `README.md`. Text is moved, never
   rewritten; links fixed both directions; link test green.
4. **BUILDLOG.** Nothing is rewritten. New entries are v2 only (tested). Add a one-paragraph
   "Reading this file" note at the top saying entries before the v2 marker are verbose
   historical narration and the snapshot table is the summary.
5. **`live-readiness-goal.md`.** Keep, banner already added. Delete nothing.

## Not in scope

- Any change under `engine/`, `sim/`, `farm/`, `server/`, or `tools/` other than a reproduced
  defect. The refactor itch is exactly what this plan exists to stop.
- "While I'm here" cleanups of test files beyond item 2.
- New tests of any kind except replacing a deleted doc test with a runtime-constant test.
- Rewriting any prose. Move, split, index, delete tests. That is all.

## Done when

- `python -m tools.metrics_snapshot --check-budget` exits 0 on four consecutive weekly
  snapshots, and `commit_shape.support_only` for the 30-day window is at most 4.
- `wc -l tests/test_docs*.py` totals under 400 lines.
- `docs/ops-runbook.md` exists and is under 400 lines; `docs/README.md` lists every doc under
  a "Current" or "History" heading.
- Full suite green with warnings as errors.

## Budget

Four sessions, at most six commits, at most 300 net non-test lines added. Items 2 and 3 are
one commit each.

## Risks

Deleting doc tests removes a guard that caught real doc staleness twice (schedule shape,
risk-control names). Mitigation: keep the runtime-constant comparisons. Rollback: git revert
of the single commit per item.
