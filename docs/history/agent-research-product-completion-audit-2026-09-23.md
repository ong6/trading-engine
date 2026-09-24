# Agent Research Product Completion Audit — 2026-09-23

## Objective and completion criteria

The programme must provide: a canonical product definition; reproducible hourly, four-hour, and
nightly agent decisions; bitemporal source evidence and exact intraday receipts; locked simulator
orders with deterministic exits and execution attribution; consistent prospective scoring and
contamination diagnostics; safe historical-data boundaries; deployment, self-test, and recovery
evidence; and explicit gates for paid data, SEC activation, brokers, and real capital.

`implemented` means source, tests, and—where applicable—live deployment were directly inspected.
`collecting` means the mechanism is deployed but calendar-dependent evidence is not mature.
`external gate` means code/acceptance criteria exist but required owner authority or external state
does not. No external gate is presented as an achieved data acquisition or performance result.

## Prompt-to-artifact checklist

| Requirement | State | Concrete artifact and verification |
|---|---|---|
| Canonical product document | implemented | `docs/product-agent-research-platform.md`; documentation/operating-contract tests |
| Reviewed model identity | implemented | `server/agent_model_client.py`; live `/agent/model/status` reports `GPT-5.6-Sol:max`, proxy/runtime/catalog hashes, no proposal tools |
| Hourly, four-hour, nightly policies | implemented | `server/agent-cadence-registration.json`; three enabled/active systemd timers; service source matches installation |
| News and standout-stock discovery | implemented | `engine/daily_opportunities.py`, `server/daily_opportunity_news.py`; latest run completed six assessments with retained news receipts |
| Multi-day alerts and fresh reassessment | implemented | `server/daily_opportunity_store.py`, `daily_opportunity_runner.py`; trigger/expiry/reassessment tests; five open and one triggered alert live |
| Typed, locked, recorded simulator trade | implemented | `daily_opportunity_tools.py`, `daily_opportunity_execution.py`; idempotency/recovery/inactive-book/next-open tests; broker route absent |
| Deterministic algo plus veto-only agent | implemented | `agent_algorithm_candidate.py`, `agent_shadow_runner.py`, `agent_veto_contract.py`; candidate immutability, buy-only veto, sell preservation, fallback tests |
| Canonical forward trace ledger | implemented/collecting | `agent_evaluation.py`; live ledger has hourly/four-hour traces and decisions; seven pre-contract artifacts skipped rather than fabricated |
| Delayed 1/5/10/20-session labels | implemented/collecting | maturity-gated gross/net return, SPY/net excess, excursion, 20 bp cost, prefix hash tests; current native windows are immature |
| Exact model/prompt/tool/input/output identity | implemented | canonical trace schema and daily/hourly artifact translators; replay-drift tests |
| Bitemporal receipt/fact envelope | implemented | `engine/bitemporal_facts.py`; exact replay, later same-value observation, revision, cutoff, missing receipt, rollback tests |
| Exact agent-visible intraday bytes | implemented | `server/intraday_source.py`, hourly observer; one-call raw-byte/fact/prompt linkage and real provider-shape smoke test |
| Security identity/history events | implemented boundary | typed listing/delisting/symbol/share-class/merger facts with stable entity/security IDs and cutoff query |
| Maximum-hold and invalidation exits | implemented | frozen horizon plus close-below-signal-low; idempotent next-open exit/retry tests; model prose cannot execute |
| Decision/tool/order/fill/cost/position/equity attribution | implemented | `daily_opportunity_execution_quality`; exact timestamp/session precision, shortfall, post-fill position/cash/equity; no fills yet live |
| Paired scoring and controls | implemented/collecting | `agent_evaluation_reporting.py`, `farm/agent_evaluation_analysis.py`; compatible-prefix pairs, long/cash controls, cohort/input/source parity |
| Accuracy/confusion/Brier/calibration/returns/drawdown/cost/latency/tokens/alerts/rates | implemented/collecting | canonical nightly JSON report; unavailable metrics are null until labels, alerts, or fills mature |
| Missing-window accounting | implemented | DST-aware registered slots and activation timestamp; due window IDs compared with canonical traces |
| Historical model diagnostic | implemented, non-promotable | original named/blinded v1 remains eight decisions; separate v2 contains twelve date-recall/order/synthetic decisions |
| Contamination suite | implemented/collecting | named/blinded, date recall, prompt permutation, and synthetic perturbation complete; post-cutoff cohort collecting |
| Vendor-neutral PIT import | implemented boundary | `engine/pit_import.py`, manifest example; audit-first/apply-explicit, checksum/license/coverage/revision/time/path/replay tests |
| Paid PIT/history acquisition | external gate | owner must set initial/recurring budget and accept vendor license; then audit a real manifest before `--apply` |
| SEC acceptance-time capture | implemented boundary / external activation gate | `tools/sec_edgar_capture.py`; fixture tests use exact `acceptanceDateTime`; live anonymous probe returned 403; require monitored email identity and successful AAPL smoke |
| Historical universe membership | external gate | current SEC ticker map explicitly lacks historical-membership authority; requires audited licensed data |
| Intraday microstructure execution | external data/authority gate | hourly/four-hour remain shadow-only; partial fills, queue position, and cancel latency require quote/trade data before intraday authority |
| Broker connectivity and real capital | external owner gate | no broker route/credentials/real money; requires separate IBKR plan and prospective evidence |
| Recovery identity and rehearsal | implemented | P8–P12 sources/services/evidence are release-bound; clean bundle `$HOME/trading-engine-p12-release3-20260923` has 57 tables and independently verifies |
| Full validation and budgets | implemented | full warnings-as-errors suite, Ruff, agent self-test, installer audit, metrics `--check-budget`; P12 layer allocations remain within caps |

## Commands and observed state

- `.venv/bin/python -m pytest -q -W error` — complete suite, warnings as errors.
- `.venv/bin/ruff check .` — static checks.
- `.venv/bin/python -m tools.self_test_daily_opportunity` — isolated end-to-end agent/tool/fill tests.
- `.venv/bin/python -m tools.install_automation` — installed-source and scheduler audit.
- `.venv/bin/python -m tools.metrics_snapshot --check-budget` — global source ceilings.
- `.venv/bin/python -m tools.backup_database verify <bundle>` — independent database/evidence verification.
- Live book: active, US$10,000 initial cash, zero agent orders/fills; simulator-only.
- Live forward evaluation: 7 native traces, 25 decisions, 100 immature horizon labels, zero mature
  labels, and performance claim `none`.
- Live provenance: 22 exact response receipts and 2,376 bitemporal facts.
- Walk-forward: 18/18 expected results, one source/data/execution cohort, zero missing/invalid/
  duplicate/config/registration mismatches, validator status `current`.
- Recovery: `$HOME/trading-engine-p12-release3-20260923`, 57 tables, approximately
  4.11 GB, independently verified; restored agent book is active with US$10,000 initial cash.
- Deployment: hourly, four-hour, and nightly timers enabled/active; latest observer service results
  successful; installed units match source.

## Honest remaining gates

1. Let post-activation native windows and 1/5/10/20-session labels mature; do not backfill missing
   pre-contract identity or tune P8/P9 mid-cohort.
2. Paid vendor ingestion remains unauthorized until an explicit spend ceiling and accepted license.
3. SEC scheduling remains disabled until a monitored `TRADING_ENGINE_SEC_USER_AGENT` passes a
   one-ticker smoke request.
4. Broker, real capital, leverage, shorts, options, and intraday execution remain unauthorized.
5. No comparative/promotion verdict before the PRD sample gates; the current report has no
   promotion authority.
