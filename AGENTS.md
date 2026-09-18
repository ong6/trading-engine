# Operating contract for agents

This file governs any LLM session in this repository (Claude Code, Codex, or another agent).
It overrides every other document except `docs/feedback.md`, where the owner's latest verdict
wins. Read it in full before doing anything. It is short on purpose.

## The mode is MAINTAIN, not BUILD

Since 2026-09-18 the engine is an **evidence-collecting appliance**. Its job is to run the
nightly, append the three frozen forward records, run the Sunday walk-forward, and stay honest.
The research verdict so far is that nothing beats its control, and the next research gates
are calendar-bound (2027 and 2029; see the backlog). Building more infrastructure does not
move those dates. The default outcome of a session is therefore **verify, report, stop**.

## Read order (five files, in this order, nothing else by default)

1. `AGENTS.md` (this file).
2. `docs/feedback.md` — the owner's verdict ledger. The newest entry overrides older docs.
3. `docs/scope.md` — what is in scope now, what is approved, what is explicitly *not yet*.
4. `data/reports/metrics/README.md` — the latest drift snapshot and budget status.
5. `docs/strategy-research-backlog.md#next-admissible-actions` — the only research queue.

Open `docs/how-it-works.md` only for the ops runbook when a scheduled run misbehaved. Do not
read `docs/live-readiness-goal.md` as a work queue; it is reference, and its workstreams C, D
and E are frozen (see `docs/scope.md`).

## Admission test for any change

Before editing anything other than a doc typo, the change must match exactly one of:

- **A row in the next-admissible-actions table** whose trigger has actually fired.
- **A plan in `docs/plans/` with `status: approved` or `active`**, and the change is inside
  that plan's stated scope.
- **A demonstrated defect**: a failing test or a reproduction command whose output is wrong,
  written into the BUILDLOG entry before the fix.

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

1. Read the five files. Run `python -m tools.metrics_snapshot --dry-run` and compare with the
   last snapshot. Query `GET /meta` if the API is up.
2. If a scheduled producer failed, fix that (it is a demonstrated defect). Otherwise apply the
   admission test to whatever you intended to do.
3. Do the one admitted thing. Run the tests it touches, then the full suite.
4. Publish the snapshot: `python -m tools.metrics_snapshot --check-budget`.
5. Append a v2 BUILDLOG entry (format below). Commit. Stop.

Do not loop. One admitted item per session. If the item is done and the tests pass, the
session is over even if context remains.

## BUILDLOG entry format v2

```
## YYYY-MM-DD — <one-line title>

- **Why:** the admission row, plan, or reproduction that admitted this work.
- **What:** two to five lines of what changed, in plain words.
- **Evidence:** the one command that proves it and its salient output line.
- **Metrics:** server/tools/product LOC deltas from the snapshot, or "unchanged".
- **Next:** the single next admitted step, or "nothing admitted".
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
