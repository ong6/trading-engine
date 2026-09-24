---
plan: P4
title: Decide whether a real broker is ever the goal
status: done
opened: 2026-09-18
owner_decision: none
---

## Decision — 2026-09-20

**Yes: real-broker operation on personal hardware remains a long-term goal.** IBKR is the primary
target because its contract identifiers and execution APIs fit a durable, broker-neutral state
machine better than a region-dependent consumer OpenAPI. Moomoo remains a fallback candidate.

This is an architecture decision, not connection authority. The next step is a separately scoped
execution-layer plan using the next free plan number (P7, because P5 and P6 already exist). Until
that plan is approved, every current freeze remains: no credentials, gateway installation, market
data subscription, adapter connection, live order, or real capital.

Completed 2026-09-20: P7 is active for an internal simulator-only three-mode paper trial. It does
not yet authorize the later IBKR-paper stage.

## Goal

The owner has written down, in `../feedback.md`, one of two decisions, and the repository
reflects it:

- **Yes, real-broker operation on personal hardware is the goal.** Then the existing agent,
  broker-paper, risk-supervisor and authority code in `server/` becomes the subject of a new
  plan with its own gates, and the ceiling on `server/` is raised for that plan only.
- **No, the engine is a research appliance.** Then `server/agent_*`, `server/broker_*`, the
  fault drills, the authority state machine, the migration tools and their tests are moved
  under `archive/execution-layer-2026-09/` with a README, exactly as the agentic layer was
  archived on 2026-09-03. Nothing is deleted. The `server` ceiling drops to the size of what
  remains.

## Why now

About 35k of the 46k lines in `server/` exist for a broker that has no authority and may
never exist. Every session that reads, tests, or hardens that code pays for it. The research
that would justify a broker (a strategy clearing its mature gate) cannot mature before
2027-09-04 (sector momentum) and may never, so the decision does not need to wait for the
evidence; it needs to be made on intent. Until it is made, the safe default is freeze.

## Scope

1. Owner writes the decision and the reasoning in `../feedback.md`.
2. If **yes**: open a new "execution layer" plan with gates copied from `../history/live-readiness-goal.md`
   workstreams C, D, E, trimmed to what a single personal account needs, and with the P1
   budget discipline. `../scope.md` moves those rows from "Not yet" to "Approved plans".
3. If **no**: one session, one commit per moved package, links fixed, tests moved with the
   code, the `server` ceiling reset in `../scope-budget.json` with the feedback entry as the
   reason. The read-only API, UI, discretionary path, risk gates for discretionary tickets,
   scheduler and driver monitors, and read models stay.

## Not in scope

- Building toward "yes" before the decision is written. The freeze in `../scope.md` holds.
- Deleting anything under either decision.
- Re-litigating the decision in a later session because a paper book had a good month.

## Done when

- A dated entry in `../feedback.md` states the decision.
- `../scope.md` has no "Not yet" rows that reference the P4 decision.
- The metrics snapshot's `server` LOC matches the decision (raised ceiling with a plan, or
  reduced after the archive move).

## Budget

Yes: one planning session. No: two sessions, under ten commits, net negative lines.

## Risks

Under "no", a future change of heart means un-archiving; the archive README should say what
each package did and which tests covered it so that is a mechanical move. Under "yes", the
main risk is the old drift resuming; P5 inherits every P1 budget.
