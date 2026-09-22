# Scope ledger

What the engine is allowed to become, and what it is not allowed to become yet. `AGENTS.md`
makes this the second thing an agent reads. Edit it only through a plan in `plans/` or an
owner entry in `feedback.md`.

## In scope now (the appliance)

| Component | Runs | Owner action if it fails |
|---|---|---|
| Nightly pipeline (`engine/run_daily.sh`) | Weekdays 22:30 UTC | Fix as a defect; reproduce first |
| Paper league day-step, 21 active books | Nightly | Same |
| Three frozen forward records: sector momentum, XS 12-1, E1 Monday | Nightly / per signal | Never touch the rule; only the monitor may append |
| Sunday walk-forward revalidation | Weekly | Same |
| Saturday verifier, Sunday liquidity refresh, Friday postflight | Weekly | Same |
| Read-only API + UI on loopback, discretionary ticket path | Continuous | Same |
| Drift metrics snapshot (`tools.metrics_snapshot`) | End of every agent session | Publish; explain any budget breach in the BUILDLOG |

Maintaining these means keeping them running unchanged. It does not mean improving them.

## Approved plans

Plans live in [`plans/`](plans/README.md). Only `approved` or `active` plans admit work. P1, P7,
P8, P9, and P10 are active; P2-P3 are approved, subject to their stated prerequisites and sequencing. P4 is done.
P5 and P6 completed on 2026-09-18; their bounded outputs remain in scope for operation and
evidence, but they authorize no further feature growth outside P7's exact trial scope.

## Not yet — frozen until its trigger fires

| Area | Current state | Trigger that unfreezes it | Until then |
|---|---|---|---|
| Agent-only / hybrid paper books (`server/agent_*`, shadow runner, proposal ledgers) | ~20k lines built, agent-only shadow timer on, no order authority | P7 only: the frozen internal simulator comparison | No work outside P7; no broker path |
| Broker-paper adapters and paper-authority state machine (`server/broker_*`) | ~15k lines built, inert; IBKR selected as eventual primary | A later, separately approved IBKR-paper plan after P7 review | No growth, credentials, gateway, or connection |
| Independent risk supervisor and fault drills | Built, inert | P7 may reuse/extend only for its internal simulator safety gates | No broker or live authority |
| Release manifest, worktree audit, backup, install-automation hardening | Working | A demonstrated recovery failure | No growth; no new invariants |
| Documentation-pinning tests (`tests/test_docs*.py`) | ~150 assertions on prose | Never | Frozen at current count |
| New league books | 21 active | A charter whose gate cleared in the backlog table | None |
| Parameter sweeps and grids | `OPEN_RECURRING_GRIDS` empty | P6 permits one pre-registered fixed-instrument experiment, not a grid | No sweep or nearby variant |
| Stock-selection or fundamentals research | Gated | 756 qualifying dates / 156 snapshots, or an audited point-in-time dataset (P3) | None |
| Intraday research | Gated | 252 qualifying sessions over 365 days in both resolutions | None |
| New API endpoints, dashboard cards, operator CLIs, migrations | — | P7/P8 name bounded status and isolated-book changes | Nothing else |
| Daily opportunity agent | Approved P8; no active runtime yet | P8's bounded simulator-only implementation | No broker path, real capital, retrospective trades, or P7 evidence pooling |
| Multi-cadence and tool-call agents | Approved P9; nightly execution policy plus shadow variants | P9's locked, attributed simulator-only implementation | No order authority for intraday variants and no broker path |

## Never on this host

Broker connections, credentials, real capital, anything that leaves the box other than public
data pushes to the configured upstream.

## Proposed, not approved

Agents append one line here instead of building. The owner promotes a line to a plan or
deletes it.

- 2026-09-18 · Split `docs/how-it-works.md` (2,247 lines) into ops runbook vs architecture
  reference. Blocked by the doc-pinning tests; needs P1 to retire them first.
- 2026-09-18 · Move dated audits under `docs/history/`. Same blocker.
