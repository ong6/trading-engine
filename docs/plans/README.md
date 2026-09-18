# Plans

One file per bounded piece of future work. A plan is the only way to admit work that is not a
backlog row or a reproduced defect (see `AGENTS.md`). Each plan has a YAML header with
`status` in `proposed | approved | active | done | dropped`; only the owner moves a plan to
`approved`. Agents may move `approved → active → done` and must record the transition in the
plan and the BUILDLOG.

| Plan | Status | One line | Owner decision needed |
|---|---|---|---|
| [P1 — Appliance mode](p1-appliance-mode.md) | proposed | Freeze growth, shrink the session loop, retire doc-pinning tests, put the box on a weekly check | Approve |
| [P2 — League collapse](p2-league-collapse.md) | proposed | Retire 11 of 21 books whose question the evidence already answered | Confirm the retire list |
| [P3 — Point-in-time data](p3-point-in-time-data.md) | proposed | Acquire and audit a survivorship-free dataset; the only lever on the 2029 gate | Pick a vendor and budget |
| [P4 — Broker decision](p4-broker-decision.md) | proposed | Decide by 2027-09 whether real-broker operation is ever the goal; until then `server/` is frozen | The decision itself |

Recommended order: P1 now, P2 the following week, P3 when the owner has picked a vendor, P4
by its date or earlier.

## Plan template

```
---
plan: P<n>
title: <short>
status: proposed
opened: YYYY-MM-DD
owner_decision: <what the owner must decide, or "none">
---

## Goal            one paragraph, what is true when this is done
## Why now         the evidence that makes this the next thing
## Scope           bullet list of the exact changes, with paths
## Not in scope    what an agent will be tempted to add, and must not
## Done when       a command and its expected output, or a metric threshold
## Budget          commits, lines, sessions
## Risks           what could go wrong and the rollback
```
