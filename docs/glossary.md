# Glossary

The engine's internal records use short codes because plans and registrations must keep stable
identities. This page gives each code a plain name. A code is a label, not a quality mark or a
claim that the work made money.

## Plans

| Code | Plain name | Meaning |
|---|---|---|
| P1 | Appliance mode | The closed plan that once framed the engine as a maintain-only service. |
| P2 | League collapse | Retires legacy paper books that no longer answer a live research question. |
| P3 | Point-in-time data | Builds survivor-aware historical membership and data inputs, using free sources first. |
| P4 | Broker decision | Records the long-term broker choice while granting no connection or trading authority. |
| P5 | Agent paper decisions | Lets one constrained agent create orders only in an isolated simulator book. |
| P6 | Alpha experiment | Ran one frozen deterministic SPY/BIL experiment and preserved its negative result. |
| P7 | Autonomous paper trial | Compares rule-only, AI-only, and hybrid allocation books on the same paper capital. |
| P8 | Daily opportunity agent | Reviews nightly market standouts and can use one locked simulator-only trade tool. |
| P9 | Multi-cadence agent tools | Adds hourly and four-hour shadow observers around the nightly agent path. |
| P10 | Contamination-aware 2022 replay | Replays a few old decisions as a diagnostic, not as evidence of predictive skill. |
| P11 | Forward agent evaluation | Joins frozen agent decisions to later outcomes in an append-only evaluation record. |
| P12 | Agent research product | Brought the agent's data, execution, evaluation, and status surfaces into one programme. |
| P13 | Market-data source hardening | Adds exact-response, research-only adapters and explicit source admission rules. |
| P14 | TradingView historical archive | Collects a resumable, survivor-biased daily-bar archive for research only. |
| P15 | Profitability evidence loop | Scores every candidate, runs paired paper books, and tests the model against a rule. |
| P16 | Challenger lab, text edge, and evaluation science | Builds shadow challengers, text labs, stronger statistics, portfolio construction, and execution measurement. |
| P17 | Personal-host IBKR paper execution | A proposed future plan for reconciling a broker paper account on personal hardware; not work for now. |
| P18 | Shared backtest core | Supplies one public point-in-time evaluator for event and portfolio studies. |

The single source of truth for plan status is [`plans/README.md`](plans/README.md). Completed plans
remain part of the system's history, but completion does not imply a profitable result.

## Workstream codes

Workstream codes are local to a plan. “W8” has no useful meaning by itself: P15 W8 is activation,
while P16 W8 is broker-paper design.

### Profitability evidence loop (P15)

| Code | Plain name | Meaning |
|---|---|---|
| W0 | Baseline and safety | Captured the starting state and fixed the authority boundary. |
| W1 | Observer evidence | Made hourly and four-hour observations pairable and complete. |
| W2 | Scoring and baseline | Added candidate-wide model scores and the deterministic comparison score. |
| W3 | Comparator books | Built AI-ranked, rule-ranked, and hybrid-veto paper books with matched mechanics. |
| W4 | Pre-open reassessment | Added a cancel-only check before pending entries reach the open. |
| W5 | Event triggers | Added shadow decisions for bounded news, filing, and intraday events. |
| W6 | Gates and reporting | Turned the registered tests into code and generated status reports. |
| W7 | Cleanup and docs | Removed replaced paths and documented the operating shape. |
| W8 | Activation | Activated the three paper books and their scoring, pre-open, and event schedules. |

### Challenger lab, text edge, and evaluation science (P16)

| Code | Plain name | Meaning |
|---|---|---|
| W0 | P15 remediation and activation | Fixed pre-activation findings, issued the registration, and activated P15. |
| W1 | Evaluation science | Adds factor-neutral measurement, sequential tests, and trial accounting. |
| W2 | Challenger lab | Runs registered shadow policies on the same candidate bundle. |
| W3 | Filing reader | Turns time-stamped filings into structured shadow decisions. |
| W4 | Historical labs | Builds time-locked text tests and post-cutoff replay diagnostics. |
| W5 | Portfolio construction | Converts model and rule scores into matched shadow portfolios. |
| W6 | Execution realism | Measures opening fills and prepares future calibration evidence. |
| W7 | Operator digest | Produces a compact weekly view of gates, books, activity, and health. |
| W8 | Stage 2 design | Describes a possible broker paper deployment without building or connecting it. |
| W9 | Cleanup, docs, and activation | Cleans the build, freezes registrations, rehearses, and activates only eligible parts. |
| W10 | Final refine pass | Reviews written outputs after activation without changing frozen evidence. |
| W11 | Synthetic proving ground | Tests whether the evaluation system finds a planted edge and rejects pure noise. |

## Research and operations terms

| Term | Plain meaning |
|---|---|
| Registration | The frozen statement of a policy, data rules, costs, test, and kill condition before evidence is seen. |
| Revision | A newly issued registration that records an allowed change; old evidence and old versions are never silently rewritten. |
| Holdout | A sealed slice of data opened once, after development choices are finished, to test whether an idea survives unseen data. |
| Census | The count of every tried policy or variant used to correct for the luck that comes from trying many ideas. |
| DSR | Deflated Sharpe ratio: a Sharpe-ratio check adjusted for the number and similarity of trials, plus non-normal returns. |
| Paper book | A simulated portfolio with orders, fills, cash, positions, and costs, but no broker connection or real money. |
| League | The nightly table that ranks active paper books by return and shows each book's result against SPY. |
| Snapshot | An immutable capture of state at a time, such as a consistent read-only database copy or a dated metrics record. |
| Evidence validator | Deterministic code that checks frozen identities, timestamps, source bytes, labels, and report inputs before evidence is accepted. |
| Walk-forward | Repeated training and evaluation across advancing time windows, so every evaluation window comes after the data used to choose the rule. |

<!-- sources: docs/plans/README.md, docs/plans/p15-profitability-evidence-loop.md, docs/plans/p16-challenger-lab-and-text-edge.md, farm/study/protocol.py, farm/study/stats.py, sim/league.py, tools/p15_evidence_validation.py, tools/publish_snapshot.py -->
