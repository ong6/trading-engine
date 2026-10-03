# Scope ledger

What the engine is allowed to become, and what it is not allowed to become yet. `AGENTS.md`
defines its place in the required read order. Edit it only through a plan in `plans/` or an
owner entry in `feedback.md`.

## In scope now (running components)

| Component | Runs | Owner action if it fails |
|---|---|---|
| Nightly pipeline (`engine/run_daily.sh`) | Weekdays 22:30 UTC | Fix as a defect; reproduce first |
| Paper league day-step (25 active books, including the three profitability evidence loop books (P15) live since 2026-09-29) | Nightly | Same |
| Three frozen forward records: sector momentum, XS 12-1, E1 Monday | Nightly / per signal | Never touch the rule; only the monitor may append |
| Sunday walk-forward revalidation | Weekly | Same |
| Saturday verifier, Sunday liquidity refresh, Friday postflight | Weekly | Same |
| Read-only API + UI on loopback, discretionary ticket path | Continuous | Same |
| Drift metrics snapshot (`tools.metrics_snapshot`) | End of every agent session | Publish; explain any budget breach in the BUILDLOG |
| Daily opportunity agent (P8) + locked simulator trade tool (`trading-engine-daily-opportunity.timer`) | 02:00 UTC Tue–Sat | Same |
| Multi-cadence agent tools (P9): hourly and four-hour shadow observers (`trading-engine-{hourly,four-hour}-opportunity.timer`) | Weekdays 10:15–16:15 hourly and 10:30/13:30 America/New_York | Same; missed windows are not replayed (`Persistent=false`) |
| Agent data capture and agent-only shadow (`trading-engine-agent-{data-capture,shadow}.timer`) | 01:25 and 01:30 UTC Tue–Sat | Same |
| Forward agent evaluation (P11) and P15 evaluation (`GET /agent/evaluation/status`, JSON and P15 Markdown reports) | After P8; refreshes after P15 scoring | Same; labels are mechanical and never tune a policy |
| P15 pre-open check, event triggers, and scoring (`trading-engine-p15-{preopen,events,scoring}.timer`) | Pre-open 09:05 and events at 09:35/09:50 then :05/:20/:35/:50 through 15:50 America/New_York on weekdays; scoring 02:30 UTC Tue–Sat | Same; revision 9 is live and no registered value may be tuned |
| TradingView historical archive (P14; existing queue, bounded slices) | 03:40, 07:40, 11:40, 21:40 and 23:40 UTC weekdays, six four-hourly slices on weekends (`trading-engine-tradingview-history.timer`); nightly enqueue is a fallback | Same; retrieval-time research only, current-universe survivor bias explicit |

Change a running component only through a plan, as a new registered version. Existing versions
and their evidence are never edited.

## Approved plans

Plan status lives in one place: the table in [`plans/README.md`](plans/README.md). Only plans
marked `approved` or `active` there admit work, subject to their stated prerequisites. The
profitability evidence loop's activation workstream (P15 W8) activated on 2026-09-29;
registration revision 9 is live as of 2026-10-02.
Completed outputs from agent paper decisions (P5), the alpha experiment (P6), the 2022 replay
(P10), forward agent evaluation (P11), the agent research product (P12), market-data source
hardening (P13), and the TradingView historical archive (P14) stay in scope for operation and
evidence but authorize no further feature growth.
P19 admits only its offline audit sidecar, JSON/Markdown renderer and fictional example. Existing
study identities, reports, holdout markers and running producers remain unchanged.
P13 TradingView capture runs for research operation; Alpaca remains gated. The P14 archive runs for
resumable current-liquid-universe daily history, isolated from operational prices and execution.
The challenger lab's evaluation through broker-paper design workstreams (P16 W1–W8) and cleanup
half of activation (W9a) are built but inactive: evaluation v2, challenger and filing paths, historical
labs, construction books, fill measurement, and the weekly digest have no authority until their
W9b registration, rehearsal, and activation gates. The Stage 2 output is design only.

## Not yet — frozen until its trigger fires

| Area | Current state | Trigger that unfreezes it | Until then |
|---|---|---|---|
| Agent-only / hybrid paper books (`server/agent_*`, shadow runner, proposal ledgers) | Agent-only shadow timer on; P8/P9 and the three P15 books (live since 2026-09-29) hold local-simulator order authority | The autonomous paper trial's (P7) frozen internal simulator comparison, P8/P9 within their locked simulator-only scope, or P15's registered comparator books | No work outside P7/P8/P9/P15; no broker path |
| Broker-paper adapters and paper-authority state machine (`server/broker_*`) | ~15k lines built, inert; IBKR selected as eventual primary | A later, separately approved IBKR-paper plan after P7 review | No growth, credentials, gateway, or connection |
| Independent risk supervisor and fault drills | Built, inert | P7 may reuse/extend only for its internal simulator safety gates | No broker or live authority |
| Release manifest, worktree audit, backup, install-automation hardening | Working; the six P15 unit files were installed and the three P15 timers enabled and added to autostart at activation on 2026-09-29 | A demonstrated recovery failure | No unrelated growth; no new invariants |
| New league books | See the metrics snapshot | A charter whose gate cleared in the backlog table | None |
| Parameter sweeps and grids | `OPEN_RECURRING_GRIDS` empty | P6 permits one pre-registered fixed-instrument experiment, not a grid | No sweep or nearby variant |
| Stock-selection or fundamentals research | Gated | 756 qualifying dates / 156 snapshots, or an audited point-in-time data (P3) dataset | None |
| Intraday research | Gated | 252 qualifying sessions over 365 days in both resolutions | None, except P15's shadow mover scan and `next_bar` labels, which are evidence collection, not research verdicts |
| New API endpoints, dashboard cards, operator CLIs, migrations | P15 extends the existing evaluation status with a bounded `p15` section | P7/P8 name bounded status and isolated-book changes; P15 names its tables and status section | Nothing else |
| Daily opportunity agent | P8 deployed and live (02:00 UTC timer) | P8's bounded simulator-only scope | No broker path, real capital, retrospective trades, or P7 evidence pooling |
| Multi-cadence and tool-call agents | P9 deployed: nightly locked simulator tool plus v5 hourly/four-hour shadow observers; P15 event triggers run in shadow since 2026-09-29 | P9's locked, attributed simulator-only scope; P15's observer fixes and shadow event triggers | No order authority for intraday variants or event triggers, and no broker path |
| Additional market-data sources | P13 deployed; TradingView active for internal research | Owner-asserted TradingView rights; Alpaca credential-gated | No operational-price overwrite, fill pricing, or execution authority |

## Never on this host

Broker connections, broker credentials, real capital, and anything that leaves the box
other than public data pushes to the configured upstream and the owner's private daily backup
of the store and research files (owner, 2026-09-29; `feedback.md`). P13 may load owner-only research-data credentials
solely for an admitted provider whose automated non-display terms were explicitly accepted.

## Proposed, not approved

Agents append one line here instead of building. The owner promotes a line to a plan or
deletes it.

- 2026-10-03 · **Raw panel duplicate detection**: a same-chunk duplicate ticker/session is overwritten; P19 validates raw audit inputs, while a separate evaluator fix remains outside P19.
- 2026-10-03 · **Terminal-zero price cross-check**: the positive-price comparison rejects a zero terminal exit; P19 preserves native zero-loss outcome evidence, while a separate cross-check change remains outside P19.

- 2026-10-02 · **Live paper book for separately held research strategies**: plan a generic,
  paper-only path from the shared backtest core into a real-time simulator book without publishing
  strategy content. This owner direction still needs a separately approved implementation plan.

## Completed from this ledger

- 2026-09-28 · Retired the prose-pinning `tests/test_docs*.py` suite and split
  `docs/how-it-works.md` into the operations runbook plus `docs/architecture-reference.md` under
  P16 W9.
- 2026-09-18 · Move dated audits under `docs/history/`. Done 2026-09-24 on owner request
  (`feedback.md`); doc tests' path constants followed the move.

<!-- sources: docs/plans/README.md, docs/plans/p15-profitability-evidence-loop.md, docs/plans/p16-challenger-lab-and-text-edge.md, server/trading-engine-p15-events.timer, server/trading-engine-tradingview-history.timer -->
