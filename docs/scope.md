# Scope ledger

What the engine is allowed to become, and what it is not allowed to become yet. Change it only
through a plan in `plans/` or an owner decision recorded in [`product.md`](product.md).

## In scope now (running components)

Live state (which books are active, the registration revision, freshness) is in `GET /meta`.

| Component | Runs | Action if it fails |
|---|---|---|
| Nightly pipeline (`engine/run_daily.sh`) | Weekdays 22:30 UTC | Fix as a defect; reproduce first |
| Paper league day-step on the engine v2 ledger, including the three P15 books | Nightly | Same |
| Late account settlement (P22, `trading-engine-accounts-settle.timer`) | 07:45 and 11:55 UTC Tue–Sat | Same; any fold, settle or verify failure halts the account |
| Hourly operations digest (P23, `trading-engine-ops-digest.timer`) with the schedule contract and the snapshot invariant monitor in shadow mode | Hourly at :08 UTC; invariants on each new snapshot | Same; shadow regressions are reported, never acted on automatically |
| Driver watchdog (`trading-engine-driver-watchdog.timer`) | Every 10 minutes from :03 UTC | Same; it may terminate a stalled driver and run one catch-up nightly |
| Auto-deployer (`trading-engine-auto-deploy.timer`) | :15, :22, :45 and :52 UTC, outside its skip windows | Same; a failed post-check rolls back automatically |
| Local retention (`trading-engine-local-prune.timer`) | Daily 12:20 UTC | Same |
| Three frozen forward records: sector momentum, XS 12-1, E1 Monday | Nightly / per signal | Never touch the rule; only the monitor may append |
| Sunday walk-forward revalidation | Weekly | Same |
| Saturday verifier, Sunday liquidity refresh, Friday postflight | Weekly | Same |
| Read-only API + UI on loopback, discretionary ticket path | Continuous | Same |
| Drift metrics snapshot (`tools.metrics_snapshot`) | End of every agent session | Publish; explain any budget breach in the BUILDLOG |
| Daily opportunity agent (P8) + locked simulator trade tool (`trading-engine-daily-opportunity.timer`) | 02:00 UTC Tue–Sat | Same |
| Multi-cadence agent tools (P9): hourly and four-hour shadow observers (`trading-engine-{hourly,four-hour}-opportunity.timer`) | Weekdays 10:15–16:15 hourly and 10:30/13:30 America/New_York | Same; missed windows are not replayed (`Persistent=false`) |
| Agent data capture and agent-only shadow (`trading-engine-agent-{data-capture,shadow}.timer`) | 01:25 and 01:30 UTC Tue–Sat | Same |
| Forward agent evaluation (P11) and P15 evaluation (`GET /agent/evaluation/status`, JSON and P15 Markdown reports) | After P8; refreshes after P15 scoring | Same; labels are mechanical and never tune a policy |
| P15 pre-open check, event triggers, and scoring (`trading-engine-p15-{preopen,events,scoring}.timer`) | Pre-open 09:05 and events at 09:35/09:50 then :05/:20/:35/:50 through 15:50 America/New_York on weekdays; scoring 02:30 UTC Tue–Sat | Same; a registration revision never changes scoring, labels, gates, schedules or frozen valid-data outcomes |
| TradingView historical archive (P14; existing queue, bounded slices) | 03:40, 07:40, 11:40, 21:40 and 23:40 UTC weekdays, six slices each weekend day (Sunday's first at 01:40) (`trading-engine-tradingview-history.timer`); nightly enqueue is a fallback | Same; retrieval-time research only, current-universe survivor bias explicit |

Change a running component only through a plan, as a new registered version. Existing versions
and their evidence are never edited. A registered source change needs a rehearsed registration
revision, never a hash-gate bypass.

## Approved plans

Plan status lives in one place: [`plans/README.md`](plans/README.md). Only plans marked `approved`
or `active` there admit work, subject to their stated prerequisites. Outputs of finished plans
(P5, P6, P10–P14, P18–P21, P23) stay in operation and evidence but authorize no further feature
growth. P16 W1–W9a are built but inactive until their W9b registration, rehearsal and activation
gates; the Stage 2 output is design only. P22 admits the generic account, fill, commission,
short/margin/PDT, halt, result-isolation and data-capture foundation; it does not admit a private
strategy, a broker connection, real capital, or options execution without bid/ask data.

## Not yet — frozen until its trigger fires

| Area | Current state | Trigger that unfreezes it | Until then |
|---|---|---|---|
| Agent-only / hybrid paper books (`server/agent_*`, shadow runner, proposal ledgers) | Agent-only shadow timer on; P8/P9 and the three P15 books hold local-simulator order authority | The autonomous paper trial's (P7) frozen internal simulator comparison, P8/P9 within their locked simulator-only scope, or P15's registered comparator books | No work outside P7/P8/P9/P15; no broker path |
| Broker-paper adapters and paper-authority state machine (`server/broker_*`) | Built, inert; IBKR selected as eventual primary | A later, separately approved IBKR-paper plan after P7 review | No growth, credentials, gateway, or connection |
| Independent risk supervisor and fault drills | Built, inert | P7 may reuse/extend only for its internal simulator safety gates | No broker or live authority |
| Release manifest, worktree audit, backup, install-automation hardening | Working | A demonstrated recovery failure, or P25's deployer | No unrelated growth; no new invariants |
| New league books | See the metrics snapshot | A charter whose gate cleared in the backlog table | None |
| Parameter sweeps and grids | `OPEN_RECURRING_GRIDS` empty | One pre-registered fixed-instrument experiment, not a grid | No sweep or nearby variant |
| Stock-selection or fundamentals research | Gated | 756 qualifying dates / 156 snapshots, or an audited point-in-time data (P3) dataset | None |
| Intraday research | Gated | 252 qualifying sessions over 365 days in both resolutions | None, except P15's shadow mover scan and `next_bar` labels, which are evidence collection, not research verdicts |
| New API endpoints, dashboard cards, operator CLIs, migrations | Only what an active plan names | A plan that names the bounded surface | Nothing else; the UI gets no new features |
| Daily opportunity agent | P8 live (02:00 UTC timer) | P8's bounded simulator-only scope | No broker path, real capital, retrospective trades, or P7 evidence pooling |
| Multi-cadence and tool-call agents | P9 nightly locked simulator tool plus hourly/four-hour shadow observers; P15 event triggers in shadow | P9's locked, attributed simulator-only scope; P15's observer fixes and shadow event triggers | No order authority for intraday variants or event triggers, and no broker path |
| Additional market-data sources | TradingView active for internal research; Alpaca dormant and credential-gated | An admitted plan and accepted non-display terms | No operational-price overwrite, fill pricing, or execution authority; no paid data or new API keys |

## Never on this host

Broker connections, broker credentials, real capital, and anything that leaves the box other than
public data pushes to the configured upstream and the owner's private daily backup of the store and
research files. Owner-only research-data credentials may be loaded solely for an admitted provider
whose automated non-display terms were accepted. Raw market data and scraped text never enter this
public repository.

## Proposed, not approved

Agents append one line here instead of building. The owner or orchestrator promotes a line to a
plan or deletes it.

- 2026-11-01 · **Pinned split adjudication:** `actions._adjudicate` rule 3 misjudges spin-off breaks when legacy refetch timestamps stand in for first acquisition (CTVA 2026-10-01, skipped with 1,848 closes still at 6.665 times the provider); classifier and spin-off semantics await a registered revision.
- 2026-11-01 · **GRML older split basis:** 40 closes before 2026-06-15 remain at 0.02 times the provider's current 1:50-adjusted history, with later history already adjusted; separate repair admission, not the real 2026-08-26 offering-day fall.
- 2026-11-01 · **Late deterministic exit intents and evaluation disclosure:** after the 2026-10-29 manual P15 run, three time-exit intents (control KOD/TXG, hybrid TXG) were written after the open their fills use, and the published evaluation report does not disclose the lost 10-28 decisions; both need a review before any change.
- 2026-10-10 · **Fail-soft exit status:** fail-soft stages and units exit 0 when they skipped work (TradingView archive under the nightly lock).
- 2026-10-02 · **Activation of separately held research strategies:** generic paper-account intake exists and new accounts start inactive; a private strategy runner or new execution instrument needs its own admitted plan and activation gates.
