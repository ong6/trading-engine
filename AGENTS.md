# Operating contract for agents

This file governs any LLM session in this repository (Claude Code, Codex, or another agent).
Read it in full before doing anything. It is short on purpose.

**Precedence:** newest `docs/feedback.md` entry > `docs/product.md` (goals, decisions, order) >
this file (how sessions work) > `docs/scope.md` (what is admitted) > everything else. Other
documents link here instead of restating the order.

## Mode: build toward a verdict

The goal is `docs/product.md`'s north star: an engine that runs on its own and makes money with
AI in the loop. Work inside an approved or active plan is BUILD work and runs until that plan's
"Done when" holds. Outside a plan, a session verifies, fixes a reproduced defect, reports, and
stops. The running producers and the calendar-bound deterministic records (E1, sector, XS) are
never disturbed by either kind of session. Model credit cost is not a reason to stop or to cut
corners (owner, 2026-09-25).

## Read order

1. `AGENTS.md` (this file).
2. The newest entries of `docs/feedback.md`, the owner's verdict ledger.
3. `docs/product.md`: north star, every owner decision, and the focus order.
4. `docs/system-blueprint.md`: what is being built and why. Read it before drafting or building
   a plan.
5. `docs/scope.md`: what is admitted now and what is frozen.
6. The active plan you are working on, or `data/reports/metrics/README.md` for a verify-only
   session.

`docs/strategy-research-backlog.md` is the queue for *deterministic* strategy research only; AI
policy work is ordered by `product.md` ("Focus now").

Open `docs/how-it-works.md` only for the ops runbook when a scheduled run misbehaved. Do not
read `docs/history/live-readiness-goal.md` as a work queue; it is reference, and its workstreams C, D
and E are frozen (see `docs/scope.md`).

## Admission test for any change

Before editing anything other than a doc typo, the change must match exactly one of:

- **A row in the next-admissible-actions table** whose trigger has actually fired.
- **A plan in `docs/plans/` with `status: approved` or `active`**, and the change is inside
  that plan's stated scope.
- **A demonstrated defect**: a failing test or a reproduction command whose output is wrong,
  written into the BUILDLOG entry before the fix. A defect is wrong behaviour or output of a
  producer, the evidence, or the simulator. Lint and complexity findings are not defects, and a
  lint cleanup never becomes a series of commits.

If none matches: do not build it. Write one line under "Proposed, not approved" in
`docs/scope.md` with the reason and stop. "Hardening", "provenance", "fail-closed",
"bounded", "identity", "consistency", and "operability" are not defects. A gap you noticed
while reading code is not a defect until it has a reproduction.

## Budgets (enforced by `tests/test_operating_contract.py`)

- **Frozen layers** cannot grow past the ceilings in `docs/scope-budget.json`: `server/`,
  `tools/`, and the research runtime (`engine/`, `sim/`, `farm/`). A change that needs a higher
  ceiling stops and asks the owner; the bump is recorded in `docs/feedback.md` first.
- **One commit per logical step, under 1,500 inserted lines** outside `data/`. Larger work
  needs an approved plan and lands as a sequence of small commits.
- **BUILDLOG entries are at most 25 lines and carry at most one SHA-256.** Identities live in
  `tools.release_manifest` output and the metrics snapshot, not in prose.
- **No new documentation-pinning tests.** Tests that assert on doc prose are frozen at their
  current count; fix a stale doc by editing the doc, not by adding a test.
- **No new endpoints, dashboards, migrations, ledgers, or operator CLIs** without a plan.

## Session shape

1. `git pull --rebase origin main`, then read the files in the read order. Run `python -m tools.metrics_snapshot --dry-run` and compare with the
   last snapshot. Query `GET /meta` if the API is up.
2. If a scheduled producer failed, fix that (it is a demonstrated defect). Otherwise apply the
   admission test to whatever you intended to do.
3. Do the one admitted thing. Run the tests it touches, then the full suite.
4. Publish the snapshot: `python -m tools.metrics_snapshot --check-budget`.
5. Append a v2 BUILDLOG entry (format below). Commit. Stop.

Never end a session with uncommitted or unstaged changes: the nightly pipeline pulls with rebase
and runs on stale code when the tree is dirty. Commits are pushed to the public upstream
automatically; commit with the repository's configured identity and add no employer or internal-tool co-author trailers.

Outside a plan: one admitted item per session, then stop. An approved or active plan with a
"How to run this plan" section is run end to end as that section says, including long sessions
and sub-agents under its one-writer rule. Never drift from the active plan into side work: a
problem found along the way that the plan does not need goes on one line under "Proposed, not
approved" in `docs/scope.md`.

## BUILDLOG entry format v2

```
## YYYY-MM-DD — <one-line title>

- **Why:** the admission row, plan, or reproduction that admitted this work.
- **What:** two to five lines of what changed, in plain words.
- **Evidence:** the one command that proves it and its salient output line.
- **Metrics:** server/tools/product LOC deltas from the snapshot, or "unchanged".
- **Next:** the single next step in the active plan, or "nothing admitted". This line records
  intent; it never admits work by itself.
```

No hashes beyond one, no PIDs, no restatement of unchanged state, no list of every gate that
still passes. The tests prove the gates; the entry records the decision.

## Feedback

When the owner reviews the repo or corrects a behaviour, the review goes in `docs/feedback.md`
as a dated entry with the rule it changes, and the rule is applied in the same session
(this file, `docs/scope.md`, or the budget). A verdict that is only remembered in
conversation is lost at the next compaction.

## Absolute rules (unchanged)

The repo is public: no employer, devbox, or internal-tool identifiers in files or commit messages, and commit dates are never rewritten. Never fabricate a price or bar. Point-in-time tables are append-only. Orders fill next-open,
never same-bar. One DuckDB writer at a time. Every strategy is pre-registered with a kill
criterion. No broker code, credentials, or real money on this host. Prove by running, not by
reading. Never weaken a gate to manufacture completion, and never tune a frozen rule after
seeing its outcome.
