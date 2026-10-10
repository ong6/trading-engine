# BUILDLOG — trading-engine

Implementation log in the v2 format defined in [`AGENTS.md`](AGENTS.md), newest entries at the
bottom. Entries before 2026-09-18 (the legacy long-form log, phase exits, environment truth, and
decisions) are preserved verbatim in
[`docs/history/buildlog-2026-07-15-to-2026-09-17.md`](docs/history/buildlog-2026-07-15-to-2026-09-17.md);
the 42-entry 2026-09-19 C90 complexity series is in
[`docs/history/buildlog-2026-09-19-c90-complexity-series.md`](docs/history/buildlog-2026-09-19-c90-complexity-series.md).

<!-- buildlog-format-v2 -->
## 2026-09-18 — Operating contract: maintain mode, scope ledger, drift metrics, plans

- **Why:** owner review of 2026-09-18 (`docs/feedback.md`): loop had drifted into building
  governance for a broker that has no authority; asked for docs, metrics and feedback layers
  that stop long LLM sessions doing work not needed yet, plus follow-up plans.
- **What:** `AGENTS.md` + `CLAUDE.md` (contract, admission test, budgets, session shape, this
  entry format); `docs/scope.md` (in scope / not yet / never / parking list);
  `docs/scope-budget.json` (LOC ceilings for `server`, `tools`, research runtime; entry budget;
  doc-test ceiling); `docs/metrics.md` + `tools/metrics_snapshot.py` publishing
  `data/reports/metrics/`; `docs/feedback.md` seeded; `docs/plans/` P1–P4 proposed;
  `tests/test_operating_contract.py` enforcing all of it; banner on `live-readiness-goal.md`.
  No runtime, strategy, evidence, schedule, or database change.
- **Evidence:** `python -m tools.metrics_snapshot --check-budget` → `budget.ok = true`;
  `pytest -q -W error tests/test_operating_contract.py tests/test_docs*.py` green. Full suite on
  macOS: 345 failures, byte-identical set on untouched HEAD (pre-existing; upstream CI on `main`
  was already red after the 2026-09-17 commit with 42 C901 errors). No new failures.
- **Metrics:** server 45,769 (unchanged) · tools +331 (this tool) · product unchanged ·
  last-10-entry mean 741 lines, 913 hashes — the baseline this format replaces.
- **Next:** nothing admitted. Owner promotes P1 (recommended) in `docs/plans/README.md`.

## 2026-09-18 — Public release: history scrubbed, visibility flipped

- **Why:** owner decision (`docs/feedback.md`, second 2026-09-18 entry) to publish the repo as a
  showcase and case-study target for junxiong.dev/trading-engine.
- **What:** history rewritten with
  `git filter-repo --replace-text` / `--replace-message` for an employer email, the host home
  path, an internal tool name and an agent co-author trailer; force-pushed; visibility public.
  201 commits, dates unchanged. Backdating was requested and refused.
- **Evidence:** fresh clone, `git log main -p | grep -ciE '<the four patterns>'` → 0;
  `gh repo view --json visibility` → PUBLIC.
- **Metrics:** unchanged (docs only).
- **Next:** nothing admitted. Existing clones (the host) must be re-cloned before the next session.

## 2026-09-18 — Resume bounded agent decisions and alpha research

- **Why:** explicit owner instruction to implement constrained agent-controlled decisions and resume algorithm alpha research.
- **What:** approved P5 for one isolated simulator-only agent decision path and P6 for one pre-registered fixed-ETF experiment; kept broker connectivity and real capital forbidden. Frozen the credit-confirmed SPY/BIL charter before its runner or result.
- **Evidence:** `pytest -q -W error` → 2,261 tests passed on the fresh rewritten-main baseline.
- **Metrics:** baseline budget green; approved ceilings recorded before implementation.
- **Next:** implement P5 without a broker submission surface.

## 2026-09-18 — Close reviewed paper-agent and alpha plans

- **Why:** active P5/P6 plus the owner's independent-review completion gate.
- **What:** added authenticated, idempotent agent-only simulator decisions with isolated attribution and no broker/live path; froze and ran one credit-confirmed SPY/BIL hypothesis. Review findings drove rerun, receipt, lifecycle, identity, and sealed-evidence fixes.
- **Evidence:** full warnings-as-errors Python suite, 54 UI tests, production UI/wheel builds, Ruff and focused runtime/evidence tests pass; P6 is `REJECT-V1` over 216 paired months.
- **Metrics:** server 46,424 · tools 6,831 · product 28,894; budget ok.
- **Next:** nothing admitted; keep the agent book paper-only and record P6 without tuning.

## 2026-09-19 — Repair stale Python dependency lock

- **Why:** demonstrated defect: `uv lock --check` exited 1 because `uv.lock` omitted the
  declared runtime dependencies `numpy>=2.0` and `PyYAML>=6.0`.
- **What:** regenerated only the dependency lock metadata from the existing requirements. No
  application, strategy, evidence, schedule, database, broker, or capital behavior changed.
- **Evidence:** `uv lock --check && uv sync --extra dev --frozen && uv run python -m pytest
  -q -W error` passed; dependency audit found no known vulnerabilities.
- **Metrics:** product and frozen runtime source unchanged; lock metadata +4 lines.
- **Next:** nothing else admitted; continue unattended evidence collection.

## 2026-09-19 — Clear the CI complexity (C90) backlog (series summary)

- **Why:** demonstrated defect: `ruff check --select C90 server tools` reported 42 functions over
  the repository CI limit of 10.
- **What:** 42 single-function refactors in `server/` and `tools/`, one commit and one entry each,
  splitting monolithic validators and orchestrators into focused helpers with no policy, authority,
  or data change. The 42 entries are preserved verbatim in
  [`docs/history/buildlog-2026-09-19-c90-complexity-series.md`](docs/history/buildlog-2026-09-19-c90-complexity-series.md).
- **Evidence:** focused tests and the full warnings-as-errors suite passed at each step; the
  repository C90 finding count fell from 42 to 0.
- **Metrics:** net server +469 LOC and tools +42 LOC across the series; product unchanged; budget
  green throughout.
- **Next:** perform the goal completion audit against current ratings and evidence.

## 2026-09-19 — Refresh source-bound fault-drill evidence

- **Why:** demonstrated operational gap: `GET /agent/fault-drills` reported `stale` after the
  reviewed source changed, so current recovery behavior was not yet attested.
- **What:** ran the frozen application state-machine drill suite and appended one source-bound,
  non-authorizing result to the existing live evidence ledger.
- **Evidence:** `python -m server.agent_fault_drills run` passed 28/28 cases with zero failures
  and zero indeterminate results; both CLI status and the API now report `current_pass`.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** audit the failed Friday miner/postflight cohort without masking upstream gaps.

## 2026-09-19 — Exclude inactive names from intraday collection

- **Why:** demonstrated defect: the live intraday selector returned 931 names including inactive
  `AVB` and `WBS`; those exact names caused the two persistent failed-ticker results.
- **What:** constrain liquidity-ranked intraday names to the current active/liquid universe while
  preserving latest-screen passers, core ETFs, append-only storage, and honest gap reporting.
- **Evidence:** focused 130 tests and the full warnings-as-errors suite pass; the live selector
  still returns 931 names but now includes zero inactive names instead of two.
- **Metrics:** engine +2 LOC; tools and product unchanged; budget remains green.
- **Next:** let the next scheduled miner verify fresh-source behavior; keep Friday failed.

## 2026-09-19 — Recover intraday miner evidence

- **Why:** the Friday farm stage lost a transient DuckDB lock race, leaving the latest intraday
  evidence at `issues`; the writer is now free and the corrected selector is deployed.
- **What:** enqueue and drain one standard intraday job through the existing guarded queue; do
  not backdate evidence or rewrite the immutable failed Friday postflight receipt.
- **Evidence:** job 511 completed with 931/931 tickers covered, zero failed tickers and batches;
  live `GET /meta` now reports the miner cohort `current` at 4/4.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** keep the historical failed Friday receipt and verify the next scheduled postflight.

## 2026-09-19 — Reload the API after verified source changes

- **Why:** demonstrated operational defect: the API process entered active state at 03:55 UTC,
  before the latest reviewed source commit at 16:43 UTC, so health was green on stale code.
- **What:** restart only the loopback user API service, then verify health, core read models, and
  the continued absence of paper/broker order routes.
- **Evidence:** the service restarted on a new process; `/health` and `/meta` return 200, fault
  drills remain `current_pass` at 28/28, and all four prohibited routes return 404.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** wait for scheduled evidence unless another defect is demonstrated.

## 2026-09-19 — Activate the approved improvement roadmap

- **Why:** the owner approved P1-P4, confirmed continued work, and authorized pushing verified
  commits to the configured upstream.
- **What:** activate P1; approve P2's listed retire set and P3/P4 subject to their explicit owner
  choices; record remote-publication authority without enabling broker or capital access.
- **Evidence:** focused documentation checks and the full warnings-as-errors suite pass; all
  static gates pass and the four plan files/index agree on their new states.
- **Metrics:** server, tools, and product unchanged; budget remains green.
- **Next:** execute P1 in its specified order, one logical change per session.

## 2026-09-20 — Select separate data and execution vendors

- **Why:** the owner delegated the provider choice, with Moomoo and IBKR as likely candidates,
  and approved choosing the system-compatible long-term direction.
- **What:** select IBKR for eventual execution, Sharadar for P3 research data, Norgate as the data
  fallback, and Moomoo as the secondary broker; keep purchase and connectivity disabled.
- **Evidence:** `uv run python -m pytest -q -W error` reached 100%; the settled 18-result
  walk-forward cohort reports `current` with one signature, and UI tests/build are green.
- **Metrics:** server, tools, and product unchanged; budget remains green.
- **Next:** resume P1; P3 waits for a spend ceiling and P4 waits for the new P7 plan.

## 2026-09-20 — Define the autonomous three-mode paper trial

- **Why:** the owner approved S$10,000 simulated starting capital, fully autonomous AI paper
  decisions, several months of observation, and comparison with algorithm and hybrid controls.
- **What:** activate P7 with three paired simulator books, frozen safety/currency contracts,
  logging and observability gates, a 90-day operational pilot, and no broker authority.
- **Evidence:** `uv run python -m pytest -q -W error` reached 100%; 54 UI tests, production build,
  operating-contract checks, static gates, and live scheduler/model-status inspection are green.
- **Metrics:** server, tools, and product unchanged; approved P7 ceilings remain green.
- **Next:** implement P7 trial identity and read-only status before any portfolio mutation.

## 2026-09-20 — Add fail-closed P7 trial readiness status

- **Why:** P7 scope item 1 requires immutable trial identity and honest activation blockers before
  any portfolio, scheduler, or simulator mutation.
- **What:** add the hash-bound three-arm manifest and one bounded read-only status route; semantic
  gates reject forged hashes, dummy books, and incompatible legacy P5 artifacts.
- **Evidence:** full warnings-as-errors suite reached 100%; live status is blocked on 13 named
  gates with no execution authority, and UI/static gates pass.
- **Metrics:** server +590, tools/product unchanged; approved P7 budget remains green.
- **Next:** freeze P7 target-choice/hold semantics and response-bound model identity contract.

## 2026-09-20 — Bind Trae observable identity for paper use

- **Why:** P7 scope item 2 and a live probe showed the model works but its bridge discarded the
  upstream family/request metadata and pinned an older CLI runtime.
- **What:** bind proxy source, runtime, catalog/routing, upstream family and request identities on
  every new response; preserve schema-v2 evidence and keep immutable revision as a live-capital gate.
- **Evidence:** real tool-free inference returned strict no-action with the complete identity; full
  Python, 11 proxy, 54 UI, production-build, and static gates pass.
- **Metrics:** server +38, tools/product unchanged; approved P7 budget remains green.
- **Next:** freeze the AI target-choice and explicit cash-versus-hold contract.

## 2026-09-20 — Define P7 tri-arm attribution contract

- **Why:** P7 requires immutable return ownership before any autonomous simulator writer exists.
- **What:** add a pure verifier for trial/cohort/arm/FX, decision, order, fill, cost, attempt,
  lifecycle, exposure, and aligned-equity evidence; no schema or live-store mutation is included.
- **Evidence:** full warnings-as-errors suite reached 100%; 31 attribution/adjacent tests, 54 UI
  tests, production build, static gates, and cross-book/cost/equity adversarial cases pass.
- **Metrics:** server +579, sim +234, tools/product unchanged; approved P7 budgets remain green.
- **Next:** implement the backup-gated atomic P7 schema and three-book initializer.

## 2026-09-22 — Repin the reviewed Trae proxy source

- **Why:** demonstrated defect: live `GET /agent/model/status` returns 503 with `Trae proxy
  source identity is invalid` after the reviewed proxy deployment changed only tool-message
  translation, leaving scheduled signal-date model decisions fail-closed.
- **What:** repin the exact deployed proxy source and update the P7 proposal/veto and manifest
  identities; the model, prompts, tool-free boundary, risk, strategy, and authority stay unchanged.
- **Evidence:** the full warnings-as-errors suite reaches 100%; live connector status now binds
  `GPT-5.6-Sol:max`, proxy 0.7, Trae CLI 0.205.1, and the reviewed source identity.
- **Metrics:** server, tools, and product LOC unchanged; budget remains green.
- **Next:** implement P7's backup-gated atomic schema and three-book initializer.

## 2026-09-22 — Approve the daily opportunity-agent plan

- **Why:** the owner directed daily market/news and standout-stock assessment with multi-day
  watches and asked for the bounded simulator implementation now.
- **What:** activate P8 with deterministic candidate ranking, structured daily model judgments,
  trigger-time reassessment, isolated next-open paper execution, and no broker authority.
- **Evidence:** the operating-contract tests pass and the raised P8 ceilings precede source work.
- **Metrics:** source LOC unchanged; server, engine, and sim ceilings raised only by the approved caps.
- **Next:** implement the deterministic daily candidate and assessment evidence core.

## 2026-09-22 — Add the daily standout assessment core

- **Why:** P8 scope items 1-4 require deterministic candidates, exact headline evidence, a
  constrained model contract, append-only outcomes, and replay before alerts can act.
- **What:** rank five liquid daily standouts from price, gap, volume, screen, earnings, and regime;
  retain bounded Yahoo responses; record validated ignore/watch/hold/swing results and alerts.
- **Evidence:** focused P8 tests prove deterministic ranking, exact news receipts, one model call,
  replay without new calls, bounded alerts, and fail-closed malformed output.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** add later-session alert evaluation, fresh reassessment, and isolated simulator orders.

## 2026-09-22 — Add P8 alert, simulator, and status boundaries

- **Why:** P8 scope items 4-6 require multi-session alert state, fresh daily reassessment, isolated
  simulator order derivation, scheduling, and bounded observability.
- **What:** add append-only alert events, later-bar crossing and session expiry, inactive-book
  initialization, capped long-only next-open intents, a status route, and a 02:00 UTC timer.
- **Evidence:** focused P8 and service tests pass alert replay, inactive-book no-order, capped active
  order, no same-day fill, attribution, and read-only status cases.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** initialize the book inactive, install the timer, run one live assessment, then validate all.

## 2026-09-22 — Deploy the daily paper observer

- **Why:** P8 scope item 6 and activation safety require scheduling, an inactive isolated book,
  recovery evidence, bounded status, and a real tool-free model observation.
- **What:** install the 02:00 UTC weekday timer, initialize a US$10k inactive book, expose status,
  and retain the first five model decisions plus two multi-session alerts with zero orders.
- **Evidence:** backup verification and focused integration tests pass; live replay reports five
  assessments, available news, zero orders, inactive book, and no broker route.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** observe daily outcomes; activate simulator execution only after final validation review.

## 2026-09-22 — Approve multi-cadence paper-agent tools

- **Why:** the owner directed hourly, multi-hour, and nightly prompt comparisons, a locked tool-call
  execution flow, self-testing, and a paired algorithm-plus-agent path.
- **What:** activate P9 with observation-only intraday variants, one nightly simulator writer,
  deterministic sizing/risk, exact replay, and a frozen gap-volume algorithm comparator.
- **Evidence:** operating-contract validation will precede P9 runtime source changes.
- **Metrics:** source LOC unchanged; approved ceilings raised by the bounded P9 allowances.
- **Next:** finish P8 validation, then implement P9's typed tool and cadence registry.

## 2026-09-22 — Add locked paper tool and cadence variants

- **Why:** P9 requires distinct hourly, four-hour, nightly, and algorithm-veto identities plus one
  durable tool boundary whose request cannot directly size or route an order.
- **What:** register four non-pooled variants, add shadow intraday observations, and require one
  exact `submit_paper_trade` call before deterministic simulator consumption.
- **Evidence:** the P8/P9 self-test passes four variants, one execution policy, the bounded tool
  schema, no broker route, and focused replay/isolation/risk tests.
- **Metrics:** included in final P8/P9 snapshot; approved caps remain green.
- **Next:** install shadow cadence timers and complete the full-suite/recovery gate.

## 2026-09-22 — Complete the multi-cadence paper-agent flow

- **Why:** P9 requires deployable shadow cadences, an exactly-once trade-tool boundary, a paired
  deterministic comparator, and a self-test before simulator authority is enabled.
- **What:** add DST-safe hourly/four-hour model observers, a durable typed-tool ledger, one exact
  assessment consumer, and a frozen gap-volume candidate with a veto-only comparison projection.
- **Evidence:** focused integration tests and the P8/P9 self-test pass, including later-open fill,
  malformed/replay/inactive-book cases, four variants, one writer, and no broker route.
- **Metrics:** server +1,468, tools +58, product +528, tests +533 since 2026-09-20; budget green.
- **Next:** run the full suite, refresh/install units, activate only the isolated simulator book.

## 2026-09-22 — Register the contaminated 2022 agent replay

- **Why:** the owner requested a few 2022 model decisions using contemporaneous charts and any
  valid fundamentals/news while explicitly accounting for possible training-data memory.
- **What:** freeze four decision dates, AAPL/MSFT/XOM/cash, a 20-session horizon, delayed outcome
  reveal, and unavailable status for the absent 2022 fundamental and news archives.
- **Evidence:** the store has 251 sessions and 3,589 current symbols in 2022 but zero 2022
  fundamentals and no timestamped 2022 news; no present data may be substituted.
- **Metrics:** source LOC unchanged; P10 uses the existing farm ceiling.
- **Next:** run and publish the price-only diagnostic without any promotion claim.

## 2026-09-22 — Run the 2022 agent replay

- **Why:** P10 permits four frozen 2022 decisions under named and blinded chart-only prompts, with
  future prices withheld and absent point-in-time fundamentals/news reported rather than invented.
- **What:** retain eight model decisions and delayed 20-session outcomes; both variants selected
  XOM four times and produced identical diagnostic results, explicitly marked contaminated.
- **Evidence:** rerun uses all retained responses with zero model calls; each variant is 3/4 correct,
  +19.78% compounded, -1.83% max drawdown, and +5.85pp mean excess versus SPY.
- **Metrics:** farm +312 lines; approved budget remains green.
- **Next:** do not promote; collect genuine prospective P8/P9 evidence and acquire audited PIT data.

## 2026-09-22 — Publish the agent-trading review

- **Why:** P8-P10 require a final evidence review separating deployed operation, simulated
  authority, historical diagnostics, and unproven performance.
- **What:** publish the architecture/control audit, correct replay drawdown and direction metrics,
  require exact tool identity, and close P10 while P8/P9 collect prospective evidence.
- **Evidence:** full warnings-as-errors suite reaches 100%; Ruff, dedicated self-test, live status,
  installed schedules, real tool transport, and retained-decision replay all pass.
- **Metrics:** final snapshot is within every approved source budget.
- **Next:** observe P8/P9 unchanged; no promotion before their frozen evidence gates.

## 2026-09-23 — Approve unified forward agent evaluation

- **Why:** the owner identified point-in-time data, execution realism, and inconsistent evaluation
  as the main blockers and asked the box to start building usable historical evidence now.
- **What:** activate P11 for one append-only cross-cadence trace ledger, delayed outcome labels,
  completeness checks, and a researched roadmap without changing P8/P9 policy rules.
- **Evidence:** live audit finds daily evidence in DuckDB, intraday evidence in JSONL, and execution
  attribution in separate ledgers with no unified delayed-label dataset.
- **Metrics:** source unchanged; approved P11 ceilings precede implementation.
- **Next:** implement canonical trace capture and maturity-gated labels.

## 2026-09-23 — Add canonical forward agent traces

- **Why:** P11 requires comparable, point-in-time evidence across daily, hourly, and four-hour
  policies instead of separate DuckDB and JSONL histories.
- **What:** add immutable trace/decision/execution-link tables, exact cutoff/latency/model identity,
  replay healing, and maturity-gated 1/5/10/20-session return and excursion labels.
- **Evidence:** focused evaluation and operations tests pass; live migration reports seven legacy
  artifacts skipped because they predate complete trace identity and creates no fabricated trace.
- **Metrics:** server/tools remain within the approved P11 ceilings.
- **Next:** capture the first native P11 windows and evaluate label completeness after maturity.

## 2026-09-23 — Add canonical forward agent traces

- **Why:** P11 requires comparable point-in-time evidence across daily, hourly, and four-hour
  policies instead of separate DuckDB and JSONL histories.
- **What:** add immutable trace/decision/execution links, exact cutoff/latency/model identity, replay
  healing, and maturity-gated 1/5/10/20-session return and excursion labels.
- **Evidence:** focused tests pass; live migration skips seven legacy artifacts lacking complete
  identity rather than fabricating traces, and initializes a clean forward cohort.
- **Metrics:** server and tools remain within the approved P11 ceilings.
- **Next:** capture the first native P11 windows and audit label coverage after maturity.

## 2026-09-23 — Publish the agent backtesting roadmap

- **Why:** P11 requires a researched, actionable roadmap across point-in-time data, execution
  realism, and consistent model evaluation before more strategy or authority expansion.
- **What:** document bitemporal data, vendor audits, execution tiers, delayed labels, paired metrics,
  contamination probes, and the phased acquisition/evaluation programme.
- **Evidence:** full suite, Ruff, dedicated agent self-test, live migration, status endpoints, and a
  verified post-migration recovery bundle all pass; seven legacy traces remain explicitly skipped.
- **Metrics:** server/tools/product remain within the approved P11 budgets.
- **Next:** let native P11 traces accumulate, then audit first 1/5/10/20-session labels.

## 2026-09-23 — Define the agent research product

- **Why:** P12 admits the owner's complete data, execution, evaluation, and historical-ingestion
  programme while retaining explicit paid-data and broker gates.
- **What:** publish the canonical PRD with users, principles, functional/nonfunctional requirements,
  success gates, phased delivery, and external authority boundaries.
- **Evidence:** operating-contract and documentation-index tests pass; P12 budgets precede source work.
- **Metrics:** source unchanged; bounded P12 ceilings are recorded in the owner ledger.
- **Next:** deliver bitemporal source receipts and execution/evaluation product phases.

## 2026-09-23 — Add bitemporal source facts

- **Why:** P12 requires immutable raw receipts and event/publication/availability/ingestion times
  before provider capture or historical imports can become evaluation evidence.
- **What:** add vendor-neutral receipt and fact tables, stable replay identities, revision chains,
  and an atomic raw-response plus normalized intraday-quote batch writer. Invalid timing, missing
  receipts, duplicate quote identities, and partial batches fail closed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error` passes at 100%, including receipt replay,
  immutable revisions, timestamp validation, centralized transactions, and rollback coverage.
- **Metrics:** server remains below 51,950 lines; all source budgets are green.
- **Next:** wire the existing intraday fetcher to preserve exact raw response bytes through P12.

## 2026-09-23 — Retain exact agent intraday responses

- **Why:** P12 requires first-class raw intraday provenance for every quote admitted to an hourly
  or four-hour agent prompt.
- **What:** replace the bounded observer's DataFrame-only quote fetch with an exact Yahoo chart
  adapter. Retain the same response bytes, request/receipt times, normalized 5-minute bars, and
  receipt hash before admitting a derived quote; malformed responses remain auditable but unusable.
- **Evidence:** the full warnings-as-errors suite passes at 100%; a live SPY probe returned one 200
  JSON response and 157 usable bars, and integration tests prove one fetch plus exact trace linkage.
- **Metrics:** server remains below 51,950 lines; all source budgets are green.
- **Next:** add deterministic maximum-hold/invalidation exits and execution-quality attribution.

## 2026-09-23 — Add deterministic agent exits and shortfall

- **Why:** P12 requires bounded maximum-hold/invalidation exits and complete execution-quality
  attribution without changing the frozen simulator or model authority.
- **What:** freeze each accepted buy's horizon and signal-day-low rule; the P8 post-step lifecycle
  creates an idempotent next-open sell on expiry or breach. Append entry/exit latency, arrival gap,
  simulated fill shortfall, cost, and honest date-only fill precision; expose bounded counts.
- **Evidence:** the full warnings-as-errors suite passes at 100%, including horizon, invalidation,
  replay, exact next-open fill, paired shortfall, and frozen forward-contract regressions.
- **Metrics:** all source ceilings remain within the approved P12 budget.
- **Next:** add paired policy scoring, calibration, missing-window, and contamination reports.

## 2026-09-23 — Add canonical agent evaluation report

- **Why:** P12 requires consistent paired scoring, calibration, coverage accounting, deterministic
  controls, execution metrics, and explicit contamination diagnostics.
- **What:** add an atomic nightly report grouped by immutable policy/model/prompt cohorts, with
  per-horizon accuracy, confusion, Brier/calibration, returns, excursions, latency, tokens, control
  deltas, compatible-window pairs, mature/immature labels, and execution/alert metrics.
- **Evidence:** focused report/CLI/service tests and the full warnings-as-errors suite pass; the live
  report truthfully shows zero native traces and four contaminated named/blinded 2022 pairs.
- **Metrics:** server/tools remain within P12 ceilings; all source budgets are green.
- **Next:** add provider-neutral PIT manifests/import validation and SEC acceptance-time capture.

## 2026-09-23 — Add point-in-time ingestion boundaries

- **Why:** P12 requires a safe vendor-neutral historical import boundary and SEC filing capture
  keyed by exact acceptance time, while paid acquisition and credentials remain owner-gated.
- **What:** add audit-first/apply-explicit manifests into isolated `pit_import_*` tables and a
  five-ticker SEC adapter retaining raw mapping/submission responses plus acceptance-time facts.
  Current SEC mappings explicitly have no historical-membership authority.
- **Evidence:** focused importer/SEC/service tests and the full warnings-as-errors suite pass; the
  live anonymous SEC probe returned 403 and therefore no failing timer or live rows were installed.
- **Metrics:** engine/server/tools remain within P12 ceilings; all source budgets are green.
- **Next:** configure a monitored SEC contact, smoke-test activation, then run final recovery audit.

## 2026-09-23 — Complete PIT and SEC ingestion contracts

- **Why:** completion audit found the initial P12 importer omitted declared coverage/revision
  semantics and could trust an incomplete replay; SEC also needs a real monitored contact identity.
- **What:** require and verify coverage, revision policy, availability policy, file containment,
  checksum, and complete replay rows. Add bounded SEC raw-response and acceptance-time capture; keep
  activation gated because this host's anonymous probe returned HTTP 403.
- **Evidence:** focused PIT/SEC tests and the full warnings-as-errors suite pass at 100%; no live
  database, operational prices, strategy state, or broker route was changed.
- **Metrics:** all source ceilings remain within the approved P12 budget.
- **Next:** run the final manifest, recovery, service, and live-state completion audit.

## 2026-09-23 — Extend recovery identity through P12

- **Why:** P12 recovery review found that the backup copied the database but its named release
  groups did not cover the new opportunity, provenance, evaluation, ingestion, and cadence files.
- **What:** add those runtime modules, tools, schedules, schema sources, and the canonical agent
  evaluation artifact to the release identity consumed by backup creation and verification.
- **Evidence:** release-manifest and backup test suites pass, including exact tree/hash verification.
- **Metrics:** tools remain below the approved P12 ceiling; all source budgets are green.
- **Next:** commit, create and verify a pre-migration backup, initialize live additive schemas, then
  create and verify the post-migration recovery bundle.

## 2026-09-23 — Fix live execution-quality reporting

- **Why:** live schema initialization reproduced a DuckDB binder error because the evaluation
  report joined two `cost_bps` columns without qualifying the selected source.
- **What:** qualify every execution-quality projection and add a row-bearing report regression test;
  regenerate the live empty-cohort report after additive P11/P12 schema initialization.
- **Evidence:** focused report tests pass and live report generation completes with zero fabricated
  traces, labels, fills, PIT imports, or SEC facts.
- **Metrics:** all source ceilings remain within the approved P12 budget.
- **Next:** finish the requirement matrix and post-schema backup/restore rehearsal.

## 2026-09-23 — Exclude agent-only books from historical replay

- **Why:** live `/meta` incorrectly expected a walk-forward artifact for the active P8 book even
  though agent decisions are retained external inputs and its registered strategy is intentionally no-op.
- **What:** classify every `agent_only_policy` configuration as forward-evaluation-only in both
  historical replay and walk-forward registries; expand recovery identity across P8-P12 sources,
  services, schedules, schema, tools, and canonical evaluation evidence.
- **Evidence:** replay, walk-forward, meta, release-manifest, and backup suites pass; shared algorithm
  behavior is unchanged and no synthetic agent result was created.
- **Metrics:** farm/tools remain within P12 ceilings; all source budgets are green.
- **Next:** refresh the affected walk-forward cohort, then perform post-schema recovery rehearsal.

## 2026-09-23 — Bring P12 within phase budgets

- **Why:** completion audit found cumulative P12 server/tool additions exceeded their stricter
  plan allocations even though repository-wide ceilings remained green.
- **What:** move generic bitemporal and intraday adapters into `engine`, consolidate the PIT CLI
  with its importer and SEC CLI with its collector, and fold report publication into its module.
  Recovery identity and the installed daily service now name the relocated files exactly.
- **Evidence:** focused provenance, ingestion, report, service, release-manifest, and backup suites
  pass; P12 net additions are server +743, engine +276, tools +324, farm +4, and sim +0.
- **Metrics:** every P12 phase allocation and repository source ceiling is green.
- **Next:** reinstall the changed service, create/verify post-schema backup, and close the audit.

## 2026-09-23 — Complete bitemporal as-of semantics

- **Why:** P12 completion audit found same-value later observations collapsed and no canonical
  cutoff query or typed security-history event boundary existed.
- **What:** preserve distinct receipt/availability observations, expose latest-revision facts only
  when both available and ingested by a requested cutoff, and validate listing, delisting, symbol,
  share-class, and merger event types through the same immutable fact contract.
- **Evidence:** focused bitemporal, intraday, SEC, and PIT suites pass, including exact replay, later
  same-value revisions, as-of selection, security-event typing, and atomic rollback.
- **Metrics:** engine remains within its P12 allocation and repository ceiling.
- **Next:** finish contamination/window diagnostics and the final recovery/completion audit.

## 2026-09-23 — Complete agent execution attribution

- **Why:** P12 completion audit found fill/cost attribution did not retain the post-fill position,
  cash, and nearest available equity state required for a complete lifecycle record.
- **What:** extend append-only execution-quality rows with post-fill quantity, cash, equity, and
  equity date; qualify joined cost fields and retain null equity honestly before end-of-day marking.
- **Evidence:** focused lifecycle/report tests and the full warnings-as-errors suite pass, including
  entry and deterministic-exit fills and a row-bearing execution report regression.
- **Metrics:** server remains within its P12 allocation and repository ceiling.
- **Next:** complete locally runnable contamination probes and scheduler-window accounting.

## 2026-09-23 — Complete evaluation coverage diagnostics

- **Why:** P12 completion audit found schedule windows uncounted, alert trigger rate mislabeled as
  precision, and three locally runnable contamination probes still marked not run.
- **What:** freeze a DST-aware evaluation start/schedule, report missing due windows, compute alert
  precision only from post-trigger outcomes, and retain separate date-recall, prompt-order, and
  synthetic-trend diagnostic artifacts without altering the original 2022 replay.
- **Evidence:** v1 eight-decision and v2 twelve-decision identities verify; focused evaluation, replay,
  service, and operating-contract suites pass. Synthetic accuracy is 25% with -11.02% compounded.
- **Metrics:** P12 net additions remain within every layer allocation and source ceiling.
- **Next:** run the final full suite, refresh/install services, verify recovery, and publish audit.

## 2026-09-23 — Close evaluation completeness gaps

- **Why:** P12 completion audit found no due-window ledger, trigger rate mislabeled as precision, and
  only the named/blinded contamination probe completed.
- **What:** freeze a DST-aware forward evaluation schedule, report missing due windows and true
  next-session alert precision, move pure analysis into `farm`, and retain separate date-recall,
  prompt-order, and synthetic-trend diagnostics without changing the original 2022 replay.
- **Evidence:** original eight and new twelve decision identities verify; focused replay/report tests
  pass. Date recall selected cash, prompt order retained XOM, synthetic accuracy fell to 25%.
- **Metrics:** every P12 layer allocation and repository source ceiling remains green.
- **Next:** regenerate one coherent final-source walk-forward cohort, full suite, and recovery bundle.

## 2026-09-23 — Add net forward outcome labels

- **Why:** P12 audit found maturity labels exposed gross returns while the product contract requires
  a frozen cost assumption for every shadow and executable decision horizon.
- **What:** retain gross returns and append explicit 20 bp round-trip cost, net return, and net
  excess fields; scoring now reads net outcomes while realized fill quality remains separately linked.
- **Evidence:** maturity/replay and report tests pass; net return is proven below gross return and
  existing zero-label live schema migrates additively without fabricated outcomes.
- **Metrics:** all P12 layer allocations and source ceilings remain green.
- **Next:** complete final full suite, cohort refresh, recovery rehearsal, and audit matrix.

## 2026-09-23 — Freeze the final P12 research source

- **Why:** P12's final evidence cohort must use one immutable runtime-source identity and the
  approved farm allocation had only two lines of remaining capacity.
- **What:** mechanically compact the pure agent-evaluation analysis module without changing its
  paired metrics, schedule coverage, or contamination semantics.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_agent_evaluation_reporting.py -W error`
  passes all seven tests and Ruff reports no findings.
- **Metrics:** farm 11,637 lines; every repository and P12 source budget remains green.
- **Next:** rebuild one uninterrupted walk-forward cohort, then close validation and recovery.

## 2026-09-23 — Complete the agent research product

- **Why:** P12 closes only after one coherent evidence cohort, live deployment audit, full tests,
  and a post-schema recovery rehearsal.
- **What:** publish the final 18-book walk-forward cohort and agent report, migrate the live schema,
  verify all cadence services, document exact product state, and preserve external authority gates.
- **Evidence:** full warnings-as-errors suite and Ruff pass; cohort is current 18/18; self-test and
  installer audit pass; the 57-table final recovery bundle verifies independently.
- **Metrics:** source unchanged at server 51,042, engine 11,871, farm 11,637, tools 7,333, sim 6,891;
  all repository and P12 allocations remain green.
- **Next:** collect prospective labels; paid data, SEC activation, and any broker work require owners.

## 2026-09-24 — Documentation cleanup, history split, and a timezone defect

- **Why:** owner request of 2026-09-24 (`docs/feedback.md`), plus a reproduction:
  `TZ=Asia/Singapore .venv/bin/python -m pytest -q tests/test_adjudicate_agent_data_discrepancy.py`
  failed with "stored provider response receipt is invalid" and passed only with `TZ=UTC`.
- **What:** receipt times are stored as naive UTC in the provider-response and independent-price
  ledgers (DuckDB shifted aware datetimes to local time). Sixteen dated snapshots and the
  pre-2026-09-18 BUILDLOG moved to `docs/history/` with an index; `docs/plans/README.md` is the
  single plan status table (P11 done); scope lists the P8/P9 timers and the P11 ledger; prose hash
  chains removed; README intro and a how-it-works agent-services section added; host wording
  scrubbed. Doc tests follow the moves; removed assertions pinned only the deleted cohort/source
  hashes (six, in two walk-forward tests).
- **Evidence:** `pytest -q -W error tests/test_operating_contract.py tests/test_docs*.py` passes;
  the reproduction passes under Asia/Singapore, America/New_York, and UTC; zero broken relative
  Markdown links.
- **Metrics:** server +2 lines (51,044); engine, sim, farm, tools unchanged; budget ok.
- **Next:** 134 other tests still fail only under a non-UTC `TZ` (agent/broker ledgers); 124 pass
  once the DuckDB session `TimeZone` is UTC, so the fix belongs at connection setup outside the
  contract-hashed `engine/lib/db.py`. Needs its own admitted pass.

## 2026-09-24 — Admit market-data source hardening

- **Why:** the owner requested Tradingview-API plus stronger realtime and historical datasets.
- **What:** open P13 for an exact-response official-API adapter and encode TradingView's current
  non-display prohibition as a hard admission gate rather than feeding it to automated decisions.
- **Evidence:** upstream source/license review and a live anonymous protocol probe establish
  technical reachability; TradingView terms explicitly bar the requested automated use.
- **Metrics:** source unchanged; P13 uses existing repository headroom with no ceiling increase.
- **Next:** implement the admitted provider boundary, fixtures, live smoke, and tonight's audit.

## 2026-09-24 — Add an admitted market-data boundary

- **Why:** P13 requires better realtime/historical inputs without allowing API availability to
  bypass market-data rights or execution boundaries.
- **What:** add a source registry, exact-response Alpaca IEX snapshot/history adapter, optional
  hourly/four-hour cross-check evidence, trace linkage, and a private environment-file hook.
  TradingView is blocked under its current non-display terms; sequence the nightly report after its
  runner to remove their reproduced DuckDB race; v3 shadow policies require fresh completed bars.
- **Evidence:** focused source/intraday/service/release tests pass; status reports Alpaca unavailable
  before network access and TradingView blocked; the 2026-09-23 nightly rerun completed six decisions.
- **Metrics:** server +487, tools +102, farm net unchanged; P13 and repository caps are green.
- **Next:** owner accepts Alpaca terms/adds credentials for a live smoke, or licenses PIT history.

## 2026-09-25 — Activate TradingView research data

- **Why:** the owner asserted the required non-display rights and directed full TradingView
  realtime/historical activation while leaving Alpaca dormant.
- **What:** implement the anonymous quote/chart WebSocket protocol directly, retain exact sent/
  received transcripts, add v4 TradingView-enabled shadow agents, and isolate historical facts.
  Stale or spreadless snapshots are stored truthfully but cannot become prompt or execution data.
- **Evidence:** live AAPL realtime and September 2022 captures succeeded; deployed v4 services exit
  successfully; focused tests and the full warnings-as-errors suite pass.
- **Metrics:** server remains within 51,950 lines; engine/farm/sim unchanged; budget green.
- **Next:** accumulate market-session v4 traces; TradingView remains research-only.

## 2026-09-25 — Admit the TradingView history archive

- **Why:** owner approval of 2026-09-25 admits P14 after the live source proof retained only 21
  AAPL bars and had no resumable universe archive.
- **What:** approve a bounded current-liquid-universe daily archive with exact transcripts,
  per-symbol/date checkpoints, queue execution, and explicit retrieval-time/survivorship limits.
- **Evidence:** `python -m tools.metrics_snapshot --dry-run` reports `budget.ok = true`.
- **Metrics:** source unchanged; P14 may use existing engine/tools headroom only.
- **Next:** implement, test, and canary the checkpointed queue worker.

## 2026-09-25 — Complete the TradingView history archive

- **Why:** active P14 required resumable broad history beyond the 21-bar AAPL source proof.
- **What:** freeze a current-liquid cohort, checkpoint bounded exact-transcript requests, expose
  failure/coverage state, add queue/miner integration and a persistent four-hour continuation timer.
  Correct TradingView ETF symbols to the live-proven `AMEX` prefix.
- **Evidence:** full warnings-as-errors suite and Ruff pass; first production slice checkpoints all
  50 windows, retains 16,573 bars, reports five empty ranges and zero failures.
- **Metrics:** engine 12,249; server 51,926; tools 7,458; all source ceilings green.
- **Next:** let the 4,063-symbol cohort accumulate; obtain survivor-free PIT membership separately.

## 2026-09-25 — Central product document and P15 profitability evidence loop

- **Why:** owner verdict 2026-09-25 (`docs/feedback.md`): one central decision document, and the AI-loop review scoped into one plan for a long-running builder session.
- **What:** `docs/direction.md` became `docs/product.md` with a decision register (made and open). P15 approved with a frozen-registration spec, workstreams W0–W8 and a run contract that allows one long session with sub-agents. Ceilings raised per the feedback entry. `scope.md`, `AGENTS.md` and the plan table point at both.
- **Evidence:** `TZ=UTC pytest -q tests` shows the same failures as the clean tree (host-only scheduler-monitor tests on a non-systemd machine); the markdown link test passes.
- **Metrics:** docs only; code LOC unchanged.
- **Next:** P15 W0 on the host.

## 2026-09-25 — Repair postflight after the fifth miner joined

- **Why:** demonstrated defect: the live five-miner `/meta` payload makes
  `_miner_receipts(...)` raise `PostflightError: canonical miner cohort is not current at 4/4`,
  so the next scheduled postflight is guaranteed to fail.
- **What:** keep the four nightly miner receipt strict while tolerating independent miners in
  `/meta`; keep the immutable 2026-09-19 failed receipt unchanged.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error` passes the full suite; the
  regression accepts a running independent archive while keeping all four nightly receipts strict.
- **Metrics:** server and product unchanged; tools -3 lines; budget ok.
- **Next:** resume P15 W0 after the scheduled-producer gate is green.

## 2026-09-26 — Restore the existing CI complexity gate

- **Why:** reproduced defect: `.venv/bin/ruff check --select C90 server tools` reports nine
  C901 errors and prevents CI from reaching the Python regression suite.
- **What:** extract existing validation and parsing steps into private helpers without changing
  admission rules, source data, simulator behavior, or execution authority.
- **Evidence:** all Ruff gates and 66 affected Python 3.12 regressions pass, including retained
  evidence, validation rejection, and next-open simulator lifecycle checks. Full local testing
  encounters existing Linux `/proc` and `flock` dependencies unavailable on macOS.
- **Metrics:** server +54, tools +12, product unchanged; all source ceilings remain green.
- **Next:** nothing admitted.

## 2026-09-25 — P15 W0: freeze the live safety baseline

- **Why:** approved P15 workstream W0 requires a clean live baseline and verified recovery point
  before its first schema change.
- **What:** verified an external recovery bundle of all 60 tables and seven operational artifacts.
  All six project timers are active and their latest service runs succeeded after the v5 observer
  repair. P8 v1 remains simulator-only at US$9,961.29 equity, one FSLY position, no pending order.
- **Evidence:** `.venv/bin/python -m tools.backup_database verify
  "$(readlink -f "$HOME")/trading-engine-p15-w0-backup-20260925-1555"` reports `status: ok`.
- **Metrics:** server +117, tools +13, product +13 since the prior snapshot; includes the first
  W1 slice and the concurrent upstream validation refactor; budget ok.
- **Next:** finish W1 common-entry pairing and delete the obsolete read-model veto lane.

## 2026-09-25 — P15 W1: repair observer evidence

- **Why:** P15 W1 reproduces whole-window loss from one stale quote, ambiguous multi-window
  pairing, incompatible entry dates, and a status-only veto lane with no book or history.
- **What:** ship v5 hourly/four-hour cohorts with explicit per-candidate unavailability; append
  common-entry v2 labels and report first-window plus all-window pairs. Remove only the obsolete
  gap-volume read model; P8 v1 and the P5/P7 algorithm candidate remain unchanged. The first live
  v5 hourly window completed 3/3 with shadow-only authority.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error` reached `[100%]` and exited 0.
- **Metrics:** server +261, tools unchanged, product +29; budget ok.
- **Next:** W2 scoring universe, prompt, baseline, ledger, and inert nightly dry-run.

## 2026-09-25 — P15 W2: build the scoring evidence loop

- **Why:** approved P15 W2 requires broad candidate scoring against a frozen deterministic
  baseline, with retained samples, point-in-time inputs, and an inert nightly delivery path.
- **What:** add the 40-mover/20-trend universe, higher-is-better baseline, truthful scoring prompt,
  three-sample durable aggregation, basis-aware labels, terminal replay, and hard noon deadline.
  The versioned service and timer remain uninstalled and excluded from autostart until W8.
- **Evidence:** `.venv/bin/python -m server.p15_scoring_runner --dry-run` completed 60 candidates
  through 18 model calls with zero unavailable outcomes and did not create live P15 tables.
- **Metrics:** server +1,014, tools +13, product +261; budget ok.
- **Next:** W3 inactive comparator books and limit-on-open simulator mechanics.

## 2026-09-25 — P15 W3: create inactive comparator books

- **Why:** approved P15 W3 requires three isolated comparator books that remain inactive until
  W8 and share one registered mechanics contract.
- **What:** add exact AI-ranked, rule-control, and hybrid-veto book definitions at US$10,000 each,
  isolated intent and position-rule evidence tables, and guarded all-or-none activation at an
  already-completed common league checkpoint. Initialization creates no runtime rows.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error tests/test_p15_books.py` passes 3 tests.
- **Metrics:** server +179, tools unchanged, product +50, tests +132; budget ok.
- **Next:** wire selection, ATR sizing/stops, SPY sleeve, time exits, and isolated P15 fills.

## 2026-09-25 — P15 W3: queue isolated comparator intents

- **Why:** approved P15 W3 requires the three books to consume one scoring window with identical
  mechanics and only their registered selection policies differing.
- **What:** consume retained P15 decisions into book-local intents; apply AI, rule, and hybrid-veto
  ranking, ATR risk sizing, 15% name and 2-entry/8-position caps, drawdown halts, deterministic
  stops/time exits, and whole-share SPY funding intents. Generic pending orders remain untouched.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error tests/test_p15_books.py` passes 5 tests.
- **Metrics:** server +216, tools/product unchanged, tests +112; budget ok.
- **Next:** execute scoped intents, persist fills/rules, rebalance SPY, and prove a full window.

## 2026-09-26 — P15 W3: execute book-local fills

- **Why:** approved P15 W3 requires next-open fills, fixed ATR stops, time exits, and an invested
  benchmark sleeve without exposing P15 intents to the generic market-order consumer.
- **What:** process only P15-owned intents with sells before stock entries and SPY last; persist
  terminal orders, costs, limit attempts and fixed stops. Limit misses keep their counterfactual
  price, cash shortages reject rather than resize, and exit proceeds rebuy whole-share SPY next open.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error tests/test_p15_books.py tests/test_p15_fills.py`
  passes 11 tests.
- **Metrics:** server +152, tools/product unchanged, tests +133; budget ok.
- **Next:** wire a copied full-window dry-run and prove non-P15 state is unchanged.

## 2026-09-26 — P15 W3: wire the scoring consumer

- **Why:** approved P15 W3 requires completed retained scores to drive only the three isolated
  comparator books and to support a complete replay-safe dry-run window.
- **What:** invoke the P15 book window after successful scoring; inactive books are a strict no-op.
  The window processes prior intents, replaces only P15 marks, queues current decisions, and is
  transactionally replay-safe without changing non-P15 portfolio or equity rows.
- **Evidence:** the full warnings-as-errors Python suite reaches `[100%]` and exits 0.
- **Metrics:** server +10, tools/product unchanged, tests +40; budget ok.
- **Next:** initialize the three live books inactive after the nightly writer releases its lock.

## 2026-09-26 — P15 W3: close comparator integrity gaps

- **Why:** independent W3 review reproduced action-field, cap, replay, activation, split, halt,
  counterfactual-label, and generic-rerun defects in the first comparator implementation.
- **What:** consume the retained decision/ATR fields, enforce caps again at fill, preserve immutable
  intent/window/fill evidence, recover P15 state after generic reruns, label misses from their
  actual attempt date, advance safety after failed scoring, and activate only a complete checkpoint.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** server +402, engine +28, tools +3, product +28, tests +332; budget ok.
- **Next:** migrate the added inactive evidence tables and repeat independent W3 review.

## 2026-09-26 — P15 W3: complete inactive comparator books

- **Why:** approved P15 W3 requires three inactive, isolated comparator books and a complete
  dry-run before pre-open work begins.
- **What:** initialize the live AI-ranked, rule-control, and hybrid-veto contracts inactive and
  empty after a verified 66-table recovery bundle. An active database copy ran real scoring into
  nine intents; a copied two-session fixture proved fills, exits, SPY, replay and isolation.
  Three independent reviewers accepted correctness, evidence integrity, and authority safety.
- **Evidence:** `.venv/bin/python -m server.p15_scoring_runner --dry-run` completed 60 candidates
  through 18 calls, retained 10 explicit unavailable outcomes, and queued nine copy-only intents.
- **Metrics:** source unchanged since the corrective snapshot; all ceilings green.
- **Next:** W4 cancel-only pre-open reassessment and counterfactual evidence.

## 2026-09-26 — P15 W4: relocate comparator mechanics

- **Why:** W4 needs server-layer headroom under the fixed 54,450-line ceiling; the completed W3
  comparator lifecycle is simulator mechanics rather than an API surface.
- **What:** move the P15 book module intact from `server/` to `sim/`, update its imports and release
  identity, and retain the same inactive live schema and behavior.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** server -928, sim +927, product +927, tools unchanged; all ceilings green.
- **Next:** implement the cancel-only P15 pre-open decision and consumer path.

## 2026-09-26 — P15 W4: add cancel-only pre-open policy

- **Why:** approved P15 W4 requires a bounded 09:05 ET reassessment that can only cancel pending
  AI and hybrid entries, while the rule book records a no-op.
- **What:** add strict tool-free keep/cancel validation, post-decision headline and event inputs,
  retained responses, fail-open lateness/errors, cancelled-order hypothetical fills and labels,
  per-order latency/shortfall evidence, and an inactive-until-W8 service/timer.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** server +463, sim +5, tools +10, product +5, tests +257; budget ok.
- **Next:** migrate the inactive W4 evidence tables and complete independent review.

## 2026-09-26 — P15 W4: close pre-open integrity gaps

- **Why:** independent W4 review reproduced cutoff, carried-intent, replay-completeness, deadline,
  and cancelled-counterfactual gaps in the first pre-open implementation.
- **What:** persist inputs and exact receipt manifests before model use; use a post-capture cutoff;
  reassess carried intents per session; backfill missed openings; bind request, response, run,
  decision and quality identities; and roll late cancellations back to deterministic keeps.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** server +208, sim/product +1, tools unchanged, tests +246; budget ok.
- **Next:** apply the inactive W4 schema after the weekly verifier releases its lock.

## 2026-09-26 — P15 W4: complete cancel-only pre-open evidence

- **Why:** approved P15 W4 requires a 09:05 ET reassessment that can only cancel, retains the
  unexecuted alternative, and measures the full decision-to-fill path.
- **What:** finish per-session carried-intent review, pre-use source retention, post-capture and
  commit-time deadlines, exact replay identities, attempt-date counterfactual labels, and latency
  and implementation-shortfall evidence. The registered unit remains uninstalled until W8.
  Three independent reviewers accepted correctness, evidence integrity, and authority safety.
- **Evidence:** the full warnings-as-errors Python suite reaches `[100%]` and exits 0.
- **Metrics:** source unchanged since the corrective snapshot; all ceilings green.
- **Next:** W5 RSS, SEC 8-K, and intraday-mover shadow event evidence.

## 2026-09-26 — P15 W5: retain text-event triggers

- **Why:** approved P15 W5 requires retained RSS and SEC 8-K sources with deterministic mapping
  and one trigger per ticker, source, and session.
- **What:** add bounded append-only RSS reads, start-at-EOF activation, exact raw receipts,
  cashtag/company-name mapping, unmatched headline retention, the P15-plus-template universe cap,
  and deduplicated RSS/8-K trigger records with no execution authority.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** engine/product +242, tools +2, server unchanged, tests +107; budget ok.
- **Next:** add the bounded intraday mover source and shadow decision/label pipeline.

## 2026-09-26 — P15 W5: add intraday mover triggers

- **Why:** approved P15 W5 requires a shadow-only mover scan across the bounded P15 and
  trend-template universe at each intraday window.
- **What:** capture up to 300 symbols plus SPY with bounded parallel reads, retain exact 5-minute
  source facts without touching operational prices, and trigger only when both the registered
  return/ATR and elapsed-session relative-volume thresholds fire.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** engine/product +144, server/tools unchanged, tests +38; budget ok.
- **Next:** persist rate-limited event decisions and both forward label bases.

## 2026-09-26 — P15 W5: close event-source integrity gaps

- **Why:** independent W5 review reproduced mutable-start, source-crash, future-session,
  concurrent-append, malformed-segment, source-identity, and cross-session dedup defects.
- **What:** add an immutable evidence start and atomic paged scan cursor; bind each event type to
  its registered producer; retain future-session triggers and malformed RSS receipts; defer bytes
  appended after open; and map every recovered fact against its point-in-time session universe.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** engine/product +182, tests +237; server, farm, sim, and tools unchanged; budget ok.
- **Next:** persist rate-limited shadow decisions, latency, and both forward label bases.

## 2026-09-26 — P15 W5: complete shadow event evidence

- **Why:** approved P15 W5 requires rate-limited shadow event decisions, latency, and independent
  next-bar and next-session-open labels for the three retained trigger sources.
- **What:** add strict tool-free event scoring in 10-name chunks, a 60-decision session cap,
  explicit unavailable and skipped outcomes, crash-safe terminal replay, and immutable decision
  latency. Label both bases independently, including terminal missing-entry paths, without order
  or portfolio authority. The service and timer remain uninstalled until W8.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** farm/product +805, server +32, tools +9, tests +527; other layers unchanged; budget ok.
- **Next:** W6 coded gates, comparisons, status projection, and generated report.

## 2026-09-26 — Exclude inactive names from scheduled fundamentals

- **Why:** `GET /meta` reported fundamentals `issues` and failed Friday postflight; the three
  failed tickers were all inactive but remained liquid, reproducing an incorrect default cohort.
- **What:** require `active = TRUE` in the scheduled liquid-universe query while preserving the
  explicitly requested ticker override. A mistaken Saturday retry was stopped after 50 durable
  rows and marked failed; that partial snapshot is retained and cannot meet the 1,000-name gate.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0; the focused
  miner/postflight suite passes 63 tests. Live confirmation waits for the next Friday producer.
- **Metrics:** engine/product +1, tests +15; server, farm, sim, and tools unchanged; budget ok.
- **Next:** resume P15 W6 after the scheduled producer reports current evidence.

## 2026-09-26 — P15 W6: code profitability gates

- **Why:** approved P15 W6 requires the primary rank test, comparator-book test, P8 review rule,
  pre-open and event scoring, and a visible count of every evaluated policy version.
- **What:** add average-tie IC, fixed 60/90/120 looks with lag-4 Newey-West bounds, forecast
  diagnostics, look-frozen book comparisons, cancellation and event metrics, the exact non-gating
  P8 review rule, and a bounded full-identity trial register. All outputs remain read-only.
- **Evidence:** `./.venv/bin/python -m pytest -q -W error` reaches `[100%]` and exits 0.
- **Metrics:** engine/product +673, tools +102, tests +357; other layers unchanged; budget ok.
- **Next:** integrate one validated projection into status and the nightly Markdown report.

## 2026-09-26 — P15 W6: publish validated evaluation status

- **Why:** approved P15 W6 requires one coded P15 status and report covering the primary test,
  books, pre-open policy, events, the frozen P8 review rule, and all evaluated policy versions.
- **What:** validate every P15 evidence chain before aggregation; expose one bounded schema-v2
  projection through the existing status route; publish JSON and Markdown atomically after P15
  scoring. Three independent reviewers accepted correctness, evidence integrity, and safety.
- **Evidence:** the focused warnings-as-errors gate reaches `[100%]`; the live read-only report
  builds with P15 inactive, P8 collecting at 3 sessions, and 12 registered trial versions.
- **Metrics:** server +388, tools +318, tests +186; engine/farm/sim unchanged; budget ok.
- **Next:** W7 remove superseded code and update product and operations documentation.

## 2026-09-26 — P15 W7: align current documentation

- **Why:** approved P15 W7 requires obsolete paths to be removed and current operations,
  scope, product state, evidence locations, and activation safeguards to agree before W8.
- **What:** confirm the superseded comparison code is already absent; retain still-used P5/P7
  contracts and legacy evidence identifiers; document W0-W7, v5 observers, three inactive P15
  books and timers, schema-v2 status/reporting, and the recovery-gated activation sequence.
- **Evidence:** the documentation, operating-contract, and service-unit tests reach `[100%]`.
- **Metrics:** code layers unchanged; documentation only; budget ok.
- **Next:** W8 frozen registration, pre-activation dry run, and safe activation.

## 2026-09-26 — P15 W8: stage the registered activation

- **Why:** approved P15 W8 requires the frozen registration and a complete dry-run day before
  activating the three comparator books or their timers.
- **What:** verify the separately committed registration; install all six staged units without
  enabling them; initialize only the empty P15 schemas under the writer lock; and rehearse the
  complete scoring and comparator flow against a database copy. The live books remain inactive,
  every P15 runtime and simulator count remains zero, and no future equity row was seeded.
- **Evidence:** `./.venv/bin/python -m server.p15_scoring_runner --dry-run` → `status: completed`,
  60 candidates, 17 model calls, nine copy-only intents, and zero fills.
- **Metrics:** source unchanged; all frozen-layer ceilings remain green.
- **Next:** run the required 2026-09-28 full dry-run day, then activate on the registered session
  only if every gate remains green.

## 2026-09-26 — P16 W1: build the evaluation foundation

- **Why:** approved P16 W1 admits evaluation science and its listed input and reporting fixes.
- **What:** add retained factor inputs, compute-time screen snapshots, paired diagnostics,
  factor adjustment, bounded sequential evidence, deflated Sharpe, and transfer calculations.
  An append-only trial catalogue counts attempted versions once, including failures and retirements.
  These modules remain inert pending integration; W1 review and registration are still open.
- **Evidence:** `.venv/bin/python -m pytest -o addopts= -q -W error tests/test_p16_*.py` → 33 passed.
- **Metrics:** server +149, tools unchanged, product +616 (engine +238, farm +378); budget ok.
- **Next:** W1 historical trial reconciliation, report integration, and independent review.

## 2026-09-26 — P16 W0: complete P15 remediation

- **Why:** approved P16 W0 admits R1–R16, its three W0 follow-ups, registration reissue, and the
  pre-activation refine gate; the later R7b owner decision supersedes the original primary test.
- **What:** close every reviewed correctness, look-ahead, statistics, recovery, and operations
  finding; reissue inactive registration revision 2 with the fixed non-overlapping primary test
  and 132-file executable closure. The final copied-store rehearsal produced 60 candidates,
  18 attempted calls (`ceil(60/10) × 3`), `unavailable_count=0`, nine queued intents, and no fills.
- **Evidence:** `./.venv/bin/pytest -q && TZ=UTC .venv/bin/pytest -q` → both reach `[100%]` and exit 0.
- **Metrics:** since 2026-09-25, server +1,648, tools +515, product +4,205; budget ok.
- **Next:** the lead may run the registered P15 activation sequence; W1 remains lead-owned.

## 2026-09-27 — P16 W0: transfer the lead to the live checkout

- **Why:** the approved P16 run was reassigned after the earlier lead stopped with work split
  across unmerged local branches.
- **What:** record `p16-sol-lead` (GPT-5.6-Sol) as the sole live-checkout lead and mark W1 as
  restarting from the salvaged branches; nightly-generated data remains untouched.
- **Evidence:** `.venv/bin/python -m tools.metrics_snapshot --dry-run` → `"ok": true` with no
  budget violations on synchronized `main`.
- **Metrics:** unchanged.
- **Next:** complete the registered P15 activation sequence, then integrate or drop every
  salvaged P16 branch.

## 2026-09-27 — P16 Phase B: dispose of the salvaged branches

- **Why:** approved P16 Phase B requires every abandoned `p16-*` branch to be integrated or
  deliberately dropped before the ordered workstreams continue.
- **What:** integrate the corrected parser, fixture, and tests from `p16-filings-draft`; its stale
  policy/transport surface was dropped. Drop `p16-census`, `p16-census-update`,
  `p16-eval-input-draft`, `p16-evaluation-store`, `p16-integration`, `p16-lead`, `p16-selection`,
  and `p16-sequential` because they overlap and the pending evaluation r3 supersedes their
  incomplete statistics, identity, and inventory contracts. Drop `p16-challenger-inputs`,
  `p16-client-draft`, and `p16-run-store` for incomplete output/receipt lineage; drop
  `p16-optimizer-draft` for obsolete solver/calibration rules; drop `p16-replay-core` and
  `p16-textlab-draft` for v3 leakage gaps; drop `p16-stage2-draft` for the accepted external draft.
- **Evidence:** host and `TZ=UTC` full suites both reach `[100%]` (3,525 tests collected);
  the parser gate passes 36 tests.
- **Metrics:** engine 14,818/16,050; server 55,364/57,050; farm 12,967/15,550;
  tools 7,996/8,850; sim 7,921/8,400; budget ok.
- **Next:** build W3 from the accepted filing design, while W1/W5 wait for evaluation r3.

## 2026-09-27 — P16 W3: build the filing reader

- **Why:** approved P16 W3 and the accepted filings design admit a fixture-backed, shadow-only
  EDGAR reader that remains inert without the configured SEC contact.
- **What:** add bounded shared retrieval, exact filing parsing and deterministic counterparts,
  append-only discovery/bundle/decision state, a provenance-bound model boundary, and host-wide
  scoring concurrency. Add point-in-time open/5-minute labels and primary, paired, sliced,
  latency-complete IC reporting; no filing decision has order authority.
- **Evidence:** `.venv/bin/python -m pytest -q && TZ=UTC .venv/bin/python -m pytest -q` → both
  reach `[100%]` with 3,619 tests collected; runtime readiness is `unconfigured` with zero calls.
- **Metrics:** engine 15,576/16,050; server 57,050/57,050; farm 13,610/15,550;
  tools 7,996/8,850; sim 7,921/8,400; budget ok.
- **Next:** build W1 evaluation science v2 from the conditionally accepted r3 design.

## 2026-09-27 — P16 W1: complete evaluation science v2

- **Why:** approved P16 W1 and the conditionally accepted evaluation v3 design admit the named
  statistical core, durable evidence state, and P16 report/status projection.
- **What:** complete factor-neutral IC, mSPRT, lifetime e-Bonferroni eligibility, canonical trial
  accounting, deflated Sharpe, and transfer metrics. Persist typed inputs, origin outcomes,
  sequential checkpoints, and family reports; extend the existing evaluation status with P16.
- **Evidence:** `.venv/bin/pytest -q` → 3,754 passed; `TZ=UTC .venv/bin/pytest -q` → 3,686 passed.
- **Metrics:** engine 15,782; farm 14,880; server 57,925; tools 7,996; sim 7,921; budget ok.
- **Next:** build W2's inert eight-policy challenger lab from the retained P15 origin bundle.

## 2026-09-27 — P16 Phase A: repair the staged P15 scoring unit

- **Why:** the approved P16 Phase A reissue admits the reproduced host failure: systemd 241
  rejects `Type=oneshot` together with `Restart=on-failure` before P15 has produced evidence.
- **What:** use `Type=exec` for P15 scoring while retaining its bounded transient-failure retry;
  run scoring then reporting through one sequential wrapper; confirm pre-open and events do not
  carry the invalid restart pattern; and make the host parser verify every P15/P16 unit together.
  Runtime evidence tables remain empty.
- **Evidence:** `.venv/bin/pytest -q tests/test_service_units.py` reaches `[100%]`, and
  `systemd-analyze --user verify` accepts all eight P15/P16 unit files.
- **Metrics:** server, tools, and product LOC unchanged; budget ok.
- **Next:** reissue inactive P15 registration revision 3 against this corrected source identity.

## 2026-09-27 — P16 Phase A: reissue the inactive P15 registration

- **Why:** the orchestrator authorized a pre-evidence revision-3 reissue after the staged scoring
  service proved invalid on this host; all P15 runtime-evidence tables remain empty.
- **What:** bind the valid sequential scoring unit, its wrapper, and the current release manifest
  into the 133-file identity; record the invalid-unit/no-evidence reason; and document that W2
  activates independently after its origin-backed rehearsal while other P16 components wait.
- **Evidence:** the P15 registration, service-unit, release-manifest, and operating-contract tests
  reach `[100%]`; systemd verifies all eight P15/P16 units together.
- **Metrics:** server and product LOC unchanged; tools +2; budget ok.
- **Next:** install the reissued inert P15 units, then resume W4's mandatory acceptance contracts.

## 2026-09-27 — P16 W4: freeze an independent lesson corpus

- **Why:** W4 mandatory condition 1 requires 100 or more plain lessons authored independently
  and frozen before the rejection bound is applied.
- **What:** freeze 120 unique, company-agnostic investment-research lessons supplied without
  repository or filter context. This commit deliberately does not run or register the filter.
- **Evidence:** the fixture-only JSON/count check reports `120 unique lessons; filter not invoked`.
- **Metrics:** product code unchanged; budget ok.
- **Next:** bind this frozen commit and fixed rejection bound, then rerun the W4 guard review.

## 2026-09-27 — P16 W4: enforce the inert replay guard boundaries

- **Why:** approved P16 W4 and its four mandatory acceptance conditions admit the replay
  evidence, price-series, notes-filter, and lockbox guard implementation before any producer run.
- **What:** bind the independent lesson corpus to the fixed rejection rule; make lockbox trial
  sets, ownership, dispatch, and event history durable and deletion-detecting; seal action-fetch
  timestamps and exact receipts; bind feature/label prices to split action sets; and reject held
  or pending quarantined splits at the P15 replay adapter boundary. The code remains inert.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_replay_{notes,lockbox,asof,store,corpus}.py`
  reaches `[100%]` with 73 passing tests.
- **Metrics:** farm 16,849; other product layers unchanged; budget ok.
- **Next:** obtain an orchestrator decision on W4's 2,000-line cap and sealed-authority boundary;
  1,949 lines are used and the estimated remaining mandatory implementation is 1,300–1,930.

## 2026-09-27 — P16 W5: compose retained construction inputs

- **Why:** approved P16 W5 and round-one review require the numerical pieces to form an inert,
  point-in-time target-to-window path while mandatory exits remain independent of risk inputs.
- **What:** compose retained origins, exact IC vectors, risk, gates, optimization, whole-share
  planning, targets, and next-session intents. Persist calibration-derived contracts, preserve
  stop/time exits through input or solver failures, and rehearse the path only in a copied store.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_{eval_inputs,optimizer,order_planner,book_store,books,runner,transfer}.py`
  reaches `[100%]` with 188 passing tests.
- **Metrics:** server +444, tools unchanged, product +136 (engine +23, farm +26, sim +87); budget ok.
- **Next:** bind complete calibration cases and execution-cost evidence, then rerun the frozen reviews.

## 2026-09-27 — P16 W5: validate calibration derivation

- **Why:** approved W5 requires lambda and turnover cost to come from retained preactivation
  inputs rather than caller-supplied scalars.
- **What:** retain canonical snapshot solver inputs, every book/snapshot/lambda result and timing,
  and both-side stock/core cost components. Recompute the curve, selected lambda, summaries, and
  maximum cost before contracts can be initialized; reject mutated evidence.
- **Evidence:** the focused W5 suite reaches `[100%]` with 189 passing tests, including adversarial
  calibration mutations.
- **Metrics:** server +241, tools unchanged, product +9 (farm +9); budget ok.
- **Next:** obtain fresh independent correctness, leakage, and authority reviews.

## 2026-09-27 — P16 W5: close calibration and window review findings

- **Why:** the second-round correctness and leakage reviews found unverified alpha derivation and
  premature completion of next-open execution windows.
- **What:** retain 120-session stock/SPY returns and recompute registered-IC alpha, covariance,
  and beta before accepting calibration; reject future or post-activation snapshots. Keep each
  construction window running until fills, accounting, labels, and close state commit together.
- **Evidence:** focused calibration, window, composition, and strict-cutoff regressions pass 6/6;
  the broader W5 suite also reaches `[100%]`.
- **Metrics:** server +29, tools unchanged, product +9 (sim +9); budget ok.
- **Next:** run the final frozen-rubric reviews and full host/UTC acceptance suites.

## 2026-09-27 — P16 W5: keep incomplete fill windows pending

- **Why:** the final correctness review reproduced a construction window completing while its
  next-open attempt remained pending because the exact-session bar was absent.
- **What:** preflight every due attempt before writing execution or book state. Keep the earliest
  incomplete window running, stop ordered catch-up there, and retry the entire window atomically
  when its exact-session inputs become available.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_books.py` reaches `[100%]` with
  10 passing tests, including a missing-bar retry with no partial ledger or state writes.
- **Metrics:** server and tools unchanged; product +24 (sim +24); budget ok.
- **Next:** run immutable final reviews and the full host/UTC acceptance suites.

## 2026-09-27 — P16 W5: close final causal and recovery gaps

- **Why:** frozen authority, correctness, and leakage reviews reproduced stale predecessor,
  retrospective fill, late quarantine/holding-state, post-activation calibration, drawdown,
  missing-bar grace, replay, and rounded-plan repair failures.
- **What:** bind claims to causal pre-open inputs and ordered predecessor state; make retries
  cutoff-stable and terminal after three sessions; reconstruct transfer holdings only from
  cutoff-visible completed book evidence; enforce preactivation/session calibration rules;
  measure first drawdown from initial capital; and apply the registered lowest-alpha SPY repair.
- **Evidence:** the focused W5 lifecycle, store, transfer, planner, and runner suite reaches
  `[100%]`, including direct regressions for every reproduced failure.
- **Metrics:** engine +23; server +111; sim +93; tools unchanged; product +116; budget ok.
- **Next:** rerun immutable frozen-rubric reviews and full host/UTC suites.

## 2026-09-27 — P16 W5: complete the inert construction checkpoint

- **Why:** approved P16 W5 and the orchestrator's checkpoint acceptance admit the completed
  causal construction path and its registered, bounded outage-recovery deviation.
- **What:** keep cutoff-visible construction state, pre-open fill refusal, split-scaled ATR,
  ordered recovery windows, and lot-keyed recovery exits. Completed retries rely on unique keys;
  W9 now owns the accepted recovery-window exit correction and three pre-activation guards.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_books.py tests/test_p16_runner.py`
  reaches `[100%]` with 28 passing tests.
- **Metrics:** unchanged.
- **Next:** complete the W4 guard fixes and simplified historical-lab implementation.

## 2026-09-27 — P16 W4: complete the replay guard checkpoint

- **Why:** approved P16 W4 and the orchestrator's guard review require fixes 1–7 and the named
  simplification before the historical-lab remainder or any producer run.
- **What:** accept ordinary lesson prose while retaining the frozen numeric/date filter; make a
  missing lockbox marker exploratory; register the one-session split sensitivity; index actions,
  adapt split rows, scope markers per experiment, and record retryable dispatch lifecycle state.
  Remove the unregistered provenance, identity, sealing, and tamper machinery named by the review.
- **Evidence:** `.venv/bin/python -m pytest -q` and `TZ=UTC .venv/bin/python -m pytest -q` both
  reach `[100%]`; the focused guard suite passes 71 tests.
- **Metrics:** farm +245; server, tools, and other product layers unchanged; budget ok.
- **Next:** build the inert W4 collectors, probes, replay/books, reduced text lab, registration,
  reports, early-close semantics, and raw-price spot check within the 3,500-line allocation.

## 2026-09-27 — P16 W4: add inert historical source collectors

- **Why:** approved P16 W4 requires the free-source collectors before coverage preflight, with
  EDGAR disabled before transport when its contact is absent.
- **What:** normalize GDELT Events/GKG, CC-NEWS, FNSPID, wires/RSS/IR, Wayback, and EDGAR fixture
  records under their registered availability rules. Keep publish-only bodies out of replay,
  bind captured bodies to archive identity, and gate EDGAR on the configured contact.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_replay_sources.py tests/test_p16_replay_corpus.py`
  passes 12 tests; Ruff passes both touched files.
- **Metrics:** farm +182; server, tools, and other product layers unchanged; budget ok.
- **Next:** add the no-call probe coverage preflight and frozen-bank contracts.

## 2026-09-27 — P16 W4: freeze contamination probe coverage

- **Why:** accepted W4 requires a no-call coverage preflight with a numeric total minimum and no
  per-category floor before any contamination probe dispatch.
- **What:** freeze receipt-backed event clusters and exact fact IDs at 300 per historical month,
  require 350 for the later unseen baseline, build deterministic private answer keys, reject
  incomplete responses as untestable, and retain the registered 0.08 pooled equivalence margin.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_replay_probes.py tests/test_p16_replay_sources.py tests/test_p16_replay_corpus.py`
  passes 19 tests; Ruff passes the touched modules.
- **Metrics:** farm +292; server, tools, and other product layers unchanged; budget ok.
- **Next:** add the isolated P15 book bootstrap, chronological replay phases, and retry tests.

## 2026-09-27 — P16 W4: run isolated replay books

- **Why:** approved W4 requires the pinned P15 book lifecycle, chronological clocks, early-close
  semantics, retry safety, isolation, and an independent raw-price spot check.
- **What:** bootstrap the exact three books behind a zero-value private anchor, run open fills and
  completed book windows at logical clocks, preserve exact retries, use the exchange early close,
  and quarantine reconstructed bars that disagree with the registered raw-price source.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_replay_runner.py tests/test_p16_replay_asof.py`
  passes 27 tests, including nine fills, marked P&L, retry identity, and anchor isolation.
- **Metrics:** farm +178; server, tools, and other product layers unchanged; budget ok.
- **Next:** add replay evaluation/reporting and the reduced, inference-unconfigured text lab.

## 2026-09-27 — P16 W4: register replay evaluation and reporting

- **Why:** approved W4 requires one registered notes endpoint, count-only reporting, and explicit
  inert authority before any historical evidence can be produced.
- **What:** bind the four replay policies, reduced text policy, report paths, code identities, and
  no-production state. Evaluate only paired factor-neutral h5 IC sessions with the registered
  five-session/10,000-draw bootstrap and render coverage, unavailable, book, price, and lockbox state.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_replay_evaluate.py tests/test_p16_replay_probes.py tests/test_p16_replay_runner.py`
  passes 13 tests; Ruff passes the touched modules.
- **Metrics:** farm +162; server, tools, and other product layers unchanged; budget ok.
- **Next:** build the reduced text-lab corpus, ridge, and unconfigured report path.

## 2026-09-27 — P16 W4: build the reduced text lab

- **Why:** approved W4 requires the reduced text-lab variant while the research-text dependency
  remains unapproved; a later checkpoint may never stand in for a missing historical checkpoint.
- **What:** inventory 2015–2025 8-K item 2.02 accessions before labels, map acceptance to the first
  strictly later NYSE open, select the fixed 25% issuer sample and four checkpoint blocks, fit
  train-only ridge inputs, and render the explicit inference-unconfigured report.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_textlab.py tests/test_p16_replay_sources.py tests/test_p16_replay_evaluate.py`
  passes 14 tests; Ruff passes the touched modules.
- **Metrics:** farm +208; server, tools, and other product layers unchanged; budget ok.
- **Next:** complete the W4 fixture suite and final host/UTC checkpoint proof.

## 2026-09-27 — P16 W4: close replay and probe integration seams

- **Why:** accepted W4 requires the replay adapter to call the pinned P15 helpers and the probe
  gate to account for finite baseline sampling before a historical dispatch is admissible.
- **What:** expose the six pure P15 scoring helpers and pinned universe/book/fill dependencies;
  add the one-sided Fisher monthly guard and exact actual-size pooled power calculation while
  preserving the frozen 300/350 coverage thresholds and 0.08 equivalence margin.
- **Evidence:** the focused replay as-of/probe suites pass 33 tests; Ruff passes all touched files.
- **Metrics:** farm +207; server, tools, and other product layers unchanged; budget ok.
- **Next:** run the complete W4 fixture suite, then the final full host/UTC suites and metrics.

## 2026-09-27 — P16 W4: verify the inert historical labs checkpoint

- **Why:** approved P16 W4 and the accepted v3 design require the named historical-lab surface
  within 5,000 production lines, followed by an orchestrator checkpoint before any real-data run.
- **What:** complete fixture-only collectors, frozen probe coverage/scoring/power, chronological
  isolated P15 books, the reduced text lab, inert registration and count-only reports, actual
  early-close clocks, and independent raw-price comparison. The deterministic fixture traverses
  HTTP collection through a 10-session split/early-close/halt replay, notes, and report twice.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_replay_e2e.py` passes twice; the
  complete W4 fixture suite and both host/UTC full suites reach `[100%]`.
- **Metrics:** W4 production Python is 3,642/5,000; budget ok.
- **Next:** orchestrator review of checkpoint W4; no W4 producer may run before acceptance.

## 2026-09-28 — P16 W4: complete the runnable replay checkpoint

- **Why:** the approved W4 plan and binding round-3 decision require phase-clock prices, in-tree
  execution, working real-format collectors, a real-path fixture, and a planned pre-probe grid.
- **What:** materialize prices incrementally at each phase clock and rewrite only split securities;
  run SCORE, PREOPEN, labels, postmortems, and lockbox/report derivation through in-tree paths.
  Stream and parse GDELT, CC-NEWS WARC, Wayback CDX, and RSS formats with durable resume ordering;
  prove the path with the deterministic 10-session fixture and keep the grid planned.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q` reaches `[100%]` with no failures.
- **Metrics:** server +0; tools +0; product +1,391 (all farm); budget ok.
- **Next:** orchestrator acceptance of checkpoint W4; no W4 producer may run before acceptance.

## 2026-09-28 — P16 W4: record orchestrator acceptance

- **Why:** the orchestrator accepted W4 for code and assigned its remaining activation and report
  conditions to W9.
- **What:** mark W4 complete and inert. W9 must gate producers on the owner's SEC contact and the
  registered price-archive listing date, and report survivor bias, conservative entity mapping,
  and CC-NEWS sidebar mis-mapping risk. A `sources.py` split remains optional cleanup.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q` reached `[100%]` with no failures in the
  accepted W4 checkpoint.
- **Metrics:** unchanged.
- **Next:** build W6 execution-realism measurement and its non-activating calibration report.

## 2026-09-28 — P16 W6: register inert fill calibration

- **Why:** approved P16 W6 and the accepted Stage 2 design require opening-fill measurement,
  chronological calibration, and a future-only v5 registration without changing P15.
- **What:** add fixed pre-open sampling and order denominators, exact three-bar and quote capture,
  append-only observations, separate held-out quote/VWAP checks, and a non-activating v5 guard.
  Register 60 training plus 20 validation sessions; keep `baseline_v1` unchanged.
- **Evidence:** `.venv/bin/python -m pytest -q` and `TZ=UTC .venv/bin/python -m pytest -q`
  both reach `[100%]`; the 16 focused W6/registration tests pass.
- **Metrics:** server +429, tools unchanged, product +497 (engine +247, farm +217, sim +33);
  budget ok.
- **Next:** build the weekly W7 operator digest on the existing status surfaces.

## 2026-09-28 — P16 W7: generate the weekly operator digest

- **Why:** approved P16 W7 requires one compact Sunday report over the existing evidence and
  health surfaces, including a prominent warning about the unversioned model catalogue alias.
- **What:** compose P15 gates/books/events, the deflated P16 leaderboard, filing/fill activity,
  producer health, and owner-needed items after walk-forward. Missing inert sources stay explicit.
- **Evidence:** `.venv/bin/python -m farm.p16_operator_digest --generated-at 2026-09-28T02:40:00+00:00`
  reports `status: complete` and writes the first 51-line weekly digest.
- **Metrics:** server/tools unchanged; product +299 (engine +4, farm +295); budget ok.
- **Next:** file the accepted Stage 2 design and its proposed P17 execution plan.

## 2026-09-28 — P16 W7: keep digest generation non-fatal

- **Why:** orchestrator review found that `set -e` let a digest error prevent the weekly report sync.
- **What:** make only the digest invocation best-effort and prove sync still runs after its failure.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_drivers.py::test_walkforward_digest_failure_is_nonfatal_and_still_syncs tests/test_p16_operator_digest.py` passes 5 tests.
- **Metrics:** product unchanged; tests +10; server and tools unchanged; budget ok.
- **Next:** complete W8's accepted Stage 2 design filing.

## 2026-09-28 — P16 W8: file the Stage 2 paper design

- **Why:** approved P16 W8 requires the accepted personal-host design and a separately proposed
  execution plan, without broker code, accounts, credentials, connections or capital.
- **What:** file the accepted design and proposed P17; incorporate cash-account, commission/budget,
  Gateway/phone, late-cancel exposure, paper-reporting, Singapore-hours, and risk-mark notes.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_operating_contract.py tests/test_docs_research_evidence.py`
  reaches `[100%]`; full host and UTC suites also reach `[100%]`.
- **Metrics:** server/tools/product unchanged; docs +713; budget ok.
- **Next:** apply the binding W6 round-2 review while the pre-11:30 UTC window remains open.

## 2026-09-28 — P16 W6: complete round-2 capture pipeline

- **Why:** the orchestrator's W6 review rejected the partial pipeline and made the end-to-end
  fixture, identity, retry, immutable-intent, quote-only, and split-rule corrections binding.
- **What:** add inert quote and Yahoo adapters, three-attempt capture, as-of liquidity, first-valid
  observation projection, failure-inclusive coverage, and atomic reports. Use quote-only fitting,
  diagnostic pinball scoring, a W9-derived 60/20 split, and keep `baseline_v1` unchanged.
- **Evidence:** `.venv/bin/python -m pytest -o addopts= -q -W error tests/test_p16_fill_capture.py tests/test_p16_fill_calibration.py tests/test_p16_fill_runner.py tests/test_p16_tradingview_intraday.py tests/test_p16_registration.py` passes 24 tests.
- **Metrics:** daily snapshot server +656, tools unchanged, product +2,931; budget ok.
- **Next:** orchestrator review of the W6 round-2 checkpoint; W9 owns activation dates and the
  documented delayed-data dry-run.

## 2026-09-28 — P16 W6: retain failed-bar measurements

- **Why:** the orchestrator accepted W6 on condition that every selected name keeps one
  best-attempt measurement even when its bars fail or remain incomplete.
- **What:** retain the best incomplete bar attempt, persist a measured failure when every attempt
  fails, and keep valid quote targets plus the cutoff-bounded liquidity tier in the observation.
  Mark W6 accepted and record the four round-2 activation follow-ups under W9.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p16_fill_runner.py` passes the fixture
  where BBB has valid quotes, failed bars, a retained quote target, and tier `gte_50m`.
- **Metrics:** server +0; tools +0; product +21 (farm); budget ok.
- **Next:** classify and fix the repository-wide Asia/Singapore failures outside P15's closure.

## 2026-09-28 — P16 W9a: make test timezones explicit

- **Why:** approved P16 W9 requires the full suite to run under Asia/Singapore without relying on
  the process timezone being UTC.
- **What:** configure every test-created DuckDB connection for UTC storage and make proposal-read
  model validation pass an aware UTC instant. Production connection setup stays frozen with P15.
- **Evidence:** `TZ=Asia/Singapore .venv/bin/pytest -q` reaches `[100%]` with no failures.
- **Metrics:** server, tools, and product unchanged; budget ok.
- **Next:** apply the W1 evaluation review fixes and required census/kill adapter wiring.

## 2026-09-28 — P16 W9a: close W1 review findings

- **Why:** approved P16 W9 lists five W1 review corrections before activation.
- **What:** remove the unregistered champion-IC gate, bind factor aggregates to their challenger
  and champion policies, and recompute stored factor reports from retained inputs before use.
  Route status through a P16-only adapter that contains P16 failures and carries primary kills.
- **Evidence:** `.venv/bin/pytest -q tests/test_p16_sequential.py tests/test_p16_evaluation_report.py tests/test_p16_store.py tests/test_p16_status_adapter.py tests/test_agent_routes.py` passes 61 tests.
- **Metrics:** server +101, tools unchanged, product +6 (farm +6); budget ok.
- **Next:** populate the canonical register from the historical P5–P16 census.

## 2026-09-28 — P16 W9a: close W5 recovery guards

- **Why:** approved P16 W9 requires three pre-activation corrections to ordered construction-book
  recovery.
- **What:** wait until a missed window's NYSE-open construction deadline; use the first completed
  P15 EOD fetch batch as the recovery cutoff and wait when a held close missed it. Queue any stop
  or time exit directly in the modeled recovery window instead of deferring it again.
- **Evidence:** `.venv/bin/pytest -q tests/test_p16_runner.py tests/test_p16_books.py` passes 39
  tests, including one behavioral test for each required guard.
- **Metrics:** server/tools unchanged; product +27 (sim); budget ok.
- **Next:** close the inert W3 activation blockers.

## 2026-09-28 — P16 W9a: close W3 activation blockers

- **Why:** approved P16 W9 requires eight filing-reader guards before any activation decision.
- **What:** add the bounded submissions scan and explicit SEC-caller inventory; derive readiness
  from that inventory so the frozen scheduled P15 direct caller keeps W3 inert. Close database
  handles around transport, sweep old queued scores FIFO, restrict liquidity work to P15/template
  names, and check next-bar price basis independently on both legs. Existing first-fetch baseline,
  unchanged-response receipt reuse, and host dispatch locking remain covered behaviorally.
- **Evidence:** `.venv/bin/pytest -o addopts= -q tests/test_p16_filing_sources.py tests/test_p16_filing_store.py tests/test_p16_filing_runner.py tests/test_p16_filing_report.py tests/test_p16_operator_digest.py tests/test_p15_registration.py tests/test_operating_contract.py` passes 100 tests.
- **Metrics:** server +124, tools unchanged, product +4 (farm +4); budget ok.
- **Next:** retire documentation-pinning tests and split the operations and architecture guides.

## 2026-09-28 — P16 W9a: load the accepted trial census

- **Why:** approved P16 W9 requires the canonical register to count every accepted P5–P16 trial;
  the orchestrator supplied the binding historical census and identity decisions.
- **What:** commit the 103-row census source, admit its `pre-plan` rows, preserve provisional
  identities, and load stable weighted contributions into the canonical register. Reconciliation
  now reports exact conservative selection-trial N=139 without inventing missing parents.
- **Evidence:** `.venv/bin/pytest -o addopts= -q tests/test_p16_trial_store.py tests/test_p16_challenger_runner.py`
  passes 24 tests, including source-row count, contribution sum, identities, and replay stability.
- **Metrics:** server +188, tools unchanged, product +18 (farm); budget ok.
- **Next:** run the full host, UTC, and Asia/Singapore suites before documentation cleanup.

## 2026-09-28 — P16 W9a: separate operations from architecture

- **Why:** approved P16 W9 carries the closed P1 documentation cleanup and requires current P16
  state in the blueprint, product, scope, and operator guide.
- **What:** replace 81 prose-pinning tests with five structural/runtime-constant checks; reduce
  `how-it-works.md` to a 224-line operations runbook and move system detail to the architecture
  reference. Record every built P16 layer as inert and leave registration/activation to W9b.
- **Evidence:** full host, `TZ=UTC`, and `TZ=Asia/Singapore` suites each pass 4,076 tests; the
  focused documentation/operating-contract suite passes 17 tests.
- **Metrics:** server, tools, and product unchanged; budget ok.
- **Next:** W9b registration, rehearsal, and activation after the scheduled P15 sequence.

## 2026-09-28 — P16 Phase A: pass the P15 pre-activation rehearsal

- **Why:** approved P16 W0 schedules the fresh recovery and copied-store P15 rehearsal one full
  dry-run day before the registration-revision-3 activation session.
- **What:** create and independently verify an external 84-table recovery bundle; run the exact
  scoring/book flow on an isolated copy at the registered pre-open cutoff. Keep all live P15
  books and timers inactive, with zero runtime evidence.
- **Evidence:** `.venv/bin/python -c '...p15_scoring_runner.dry_run(now=2026-09-28T11:00Z)...'`
  completed 60 candidates, 18 calls, zero unavailable outcomes, and nine copy-only intents.
- **Metrics:** server, tools, and product unchanged; budget ok.
- **Next:** activate P15 revision 3 on 2026-09-29 before its first timer, then verify cycle one.

## 2026-09-29 — P16 W0: activate P15 revision 3

- **Why:** approved P16 W0 and P15 W8 schedule the separately registered activation after one
  full dry-run day and before the first September 29 P15 window.
- **What:** verify a fresh external recovery bundle; atomically activate the three empty P15
  books at the common 2026-09-28 checkpoint; and add only their three timers to autostart.
  Install and enable the matching units while the P16 challenger timer remains inert.
- **Evidence:** `GET /agent/evaluation/status` returns HTTP 200 with all three P15 books active;
  installed-unit verification and the timer list show all three timers enabled and waiting.
- **Metrics:** server and product unchanged; tools +3; budget ok.
- **Next:** verify the first pre-open, event, and scoring cycles through 2026-10-01.

## 2026-09-29 — Docs: record live P15 state and the research funnel

- **Why:** doc defect: README, `product.md`, `scope.md`, the blueprint, and the architecture
  reference still described P15 as inactive after its 2026-09-29 activation.
- **What:** corrected the P15 state and active-book count in five docs and the timer table;
  refreshed "Where it stands" and "Focus now"; added the screen/confirm/book research funnel
  to the blueprint; listed the P15 timers as running components; and parked the private
  strategy plug-in boundary under "Proposed, not approved".
- **Evidence:** `SELECT count(*) FILTER (WHERE active) FROM portfolios` returns 25; the
  documentation-integrity and operating-contract tests pass.
- **Metrics:** unchanged (docs only).
- **Next:** P15 first-cycle checks through 2026-10-01, then P16 W9b.

## 2026-09-29 — Record the owner's private off-host backup decision

- **Why:** owner decision (`feedback.md`, 2026-09-29): the store and research files may leave
  the host for a private backup repository.
- **What:** recorded the decision and its rules in `feedback.md`, the "Never on this host" rule
  in `scope.md`, and the decisions table in `product.md`. The backup runs from a separate private
  repository and uses only the existing `tools.backup_database` command; no engine code changed.
- **Evidence:** a fresh clone of the backup on a second machine restored all 90 tables with every
  checksum matching the live copy.
- **Metrics:** unchanged (docs only).
- **Next:** P15 first-cycle checks through 2026-10-01, then P16 W9b.

## 2026-09-29 — Keep TradingView archive work clear of P15

- **Why:** jobs 618 and 619 failed inside the 15:50 and 19:50 UTC P15 event windows; their
  retained attempts report DuckDB conflicting-writer locks, and an isolated real child exited 1
  after 55.5 seconds with the production 60-second default. Nightly job 623 and the 23:48 timer
  job 624 both completed off-window. The fundamentals alert is a false alarm: scheduled Friday
  job 573 stored 4,097 names, while manually stopped Saturday retry 575 also caused the September
  26 postflight failure and will clear after the October 2 scheduled run. The only queue failure
  classification is for closed sweeps, so job 575 remains unchanged.
- **What:** move weekday archive slices to 03:40, 07:40, 11:40, 21:40 and 23:40 UTC while retaining
  six four-hourly weekend slices. Give the timer child the parent's 900-second bounded reconnect
  window and append its stdout and stderr to `logs/tradingview-history.log`.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_queue_runner.py tests/test_service_units.py tests/test_install_automation.py`
  passes at 100%; the installed-unit audit and `systemd-analyze verify` both pass.
- **Metrics:** server, tools, and product unchanged; tests +34; budget ok.
- **Next:** verify the remaining 03:40, 07:40 and 11:40 UTC archive slices, then continue the P15
  first-cycle checks through October 1.

## 2026-09-30 — Keep common-entry labels valid after bar refreshes

- **Why:** the September 30 report refresh reproduced `common-entry label evidence differs`
  after the nightly price upsert replaced the bars' `fetched_at` timestamps.
- **What:** prove schema-2 label availability from the retained label body and price-prefix hash;
  validate its session calendar against current SPY dates; and count current source revisions
  without changing the recorded label, scoring, books, gates, or evidence statistics.
  Issue registration revision 4 and expose the revision count and label ids in status and reports.
- **Evidence:** read-only copied-store validation passes all 22 common-entry labels and reports
  `labels_source_revised=16`; the full 4,084-test suite and whole-repository Ruff check pass.
- **Metrics:** server +7, tools +7, product unchanged; budget ok.
- **Next:** deploy registration revision 4 after the P15 window, refresh the report, and verify CI.

## 2026-09-30 — Clear newly published dependency advisories

- **Why:** CI run 36770464908 failed its two blocking audits after new advisories marked
  urllib3 2.7.0 and Next.js 16.3.4 vulnerable; the P15 deployment requires green CI.
- **What:** update only the Python lock to urllib3 2.8.0 and the UI manifest and lock to
  Next.js 16.3.8. No engine, strategy, registration, or evidence code changed.
- **Evidence:** the exact CI pip and npm audits report no known vulnerabilities; all 54 UI tests
  and the production UI build pass.
- **Metrics:** server, tools, and product unchanged.
- **Next:** rerun CI for the deployed P15 registration revision 4.

## 2026-09-30 — Mark P15 active after the first scoring cycle

- **Why:** P15 W8 permits the active transition after a scoring cycle refreshes the report while
  the pre-open and event cycles remain green; revision 4 landed as the validator-only fix.
- **What:** verified revision 4 against the checkout and the completed 18-sample scoring run;
  refreshed the report and status; and marked P15 active in the plan and product records.
- **Evidence:** `.venv/bin/python -m server.agent_evaluation_reporting` exited 0 with
  `status: complete` and `trace_count: 51`; the refreshed P15 report is collecting.
- **Metrics:** server, tools, and product unchanged; budget ok.
- **Next:** P16 W9b registration and rehearsals.

## 2026-10-01 — Map filled P15 intents to simulator order status

- **Why:** scoring run 2 completed, but its report reproduced `P15 book runtime evidence differs`:
  all nine mismatches were intent status `filled` against simulator status `p15_filled`.
- **What:** map only filled intent status to the simulator's registered filled status during the
  runtime cross-check; retain every other field and status comparison unchanged. Add passing and
  rejecting regression fixtures, and issue registration revision 5 without changing written rows.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_agent_evaluation_reporting.py
  -k 'book_runtime'` passes both status-mapping regression tests.
- **Metrics:** server +2; tools and product unchanged; budget ok.
- **Next:** P16 W9b registration and rehearsals.

## 2026-10-01 — Recover event-label sources across later revisions

- **Why:** after the book fix, reporting reproduced `P15 event label evidence differs`; the
  original daily-row cutoff was empty after refresh even though the revision-26 IOVA/SPY facts
  visible at labeling exactly reproduced the stored source prefix.
- **What:** validate the exact intraday revisions visible at label time, their first availability,
  five-minute close, fact identities, label body, and source prefix. Count intact timely labels
  whose exact sources cannot be recovered, keep look-ahead fail-closed, and issue revision 6.
  No labeler, written row, scoring, book, or gate changed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_p15_event_runner.py -k
  'event_label_validation'` passes all four source-revision, look-ahead, and tamper regressions.
- **Metrics:** server +12, tools +184, product unchanged; budget ok.
- **Next:** P16 W9b registration and rehearsals.

## 2026-10-01 — Refresh league evidence after P15 book windows

- **Why:** after the October 1 scoring run finalized the September 30 P15 book windows, `/meta`
  reproduced `nightly_evidence: invalid` because `league.csv` still held the nightly's earlier
  equity values.
- **What:** make scoring re-render both league files through the nightly's existing idempotent
  renderer after evaluation reporting, with any failure failing the service. Add a regression for
  stale post-render P15 equity, restored validation, and byte-identical repeat output; issue
  registration revision 7. Queue jobs 618/619 remain unchanged because no supported path
  supersedes failed rows.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_nightly_reports.py -k
  'p15_equity_update_requires_league_rerender'` passes.
- **Metrics:** server, tools, and product unchanged; budget ok.
- **Next:** P16 W9b registration and rehearsals.

## 2026-10-01 — Establish P3 free-source survivor audit

- **Why:** approved P3 Phase 0 implements the owner's free-source decision while paid vendor
  purchase remains blocked.
- **What:** capture and idempotently load Tiingo's public US stock intervals into an isolated
  database; add a fixture-tested, resumable Massive grouped-daily fetcher that remains unrun;
  and publish the 2010–2026 exact-ticker survivor-gap audit from a consistent store copy.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` passes all 4,105 collected tests;
  whole-repository Ruff and the metrics budget check pass.
- **Metrics:** since 2026-09-30, server +14, tools +664, product +265; budget ok.
- **Next:** owner supplies a Massive free key, then SEC contact identity; paid vendor spend remains
  blocked.

## 2026-10-01 — Approve the shared backtest core plan

- **Why:** the owner's 2026-10-01 approval admitted P18 and fixed its design and three
  checkpoints.
- **What:** add the approved P18 plan with the reuse map, scope, acceptance gates, risks, and
  budget; publish the common backtest standard; and record the plan, budget, and decision in the
  repository indexes. No runtime, strategy, service, registration, or live data changed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` passes at 100%; whole-repository
  Ruff also passes.
- **Metrics:** server, tools, product, and tests unchanged; budget ok.
- **Next:** after orchestrator `go`, implement P18 items 1–7 and stop at checkpoint `p18-core`.

## 2026-10-01 — Build the shared study core

- **Why:** active P18 items 1–7 after the orchestrator accepted `p18-plan` and directed `go`.
- **What:** add declarative event/portfolio specs, hard-bounded point-in-time primary and
  independent-secondary data, listing/liquidity/delisting handling, the four exact hashed cost
  profiles, gross benchmarks, calendar-session statistics, sealed holdouts, run identity, and the
  study-owned census schema. Tighten the P18 budget and leave all existing runtime paths unchanged.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` passes at 100%; 25 focused study
  tests and whole-repository Ruff also pass.
- **Metrics:** farm/product +1,123; tests +441; server and tools unchanged; budget ok.
- **Next:** after orchestrator `go`, implement P18 items 8–11.

## 2026-10-01 — Complete the shared study evaluator

- **Why:** active P18 items 8–11 after the orchestrator accepted `p18-core` and directed `go`.
- **What:** add deterministic process-pool execution, fixed atomic reports with independent-price
  recomputation, a seeded price-only proving ground, and the runnable SPY 200-session trend
  example. Register `baseline_v1` by direct delegation without changing its established identity.
- **Evidence:** 45 focused tests and the full parallel suite pass; power is 48/50, null size is
  7/200 inside the exact 99% band [3, 19], all canaries pass, serial/parallel bytes match, and
  whole-repository Ruff passes.
- **Metrics:** farm/product +1,865 and tests +610 for P18; server and tools unchanged; budget ok.
- **Next:** nothing admitted.

## 2026-10-01 — Add native P18 strategy simulation

- **Why:** the approved P18 native-simulation follow-up admitted the missing shared evaluation
  path, conditional exits, and study-private point-in-time inputs.
- **What:** simulate event orders and portfolio targets into stable, costed ledgers; gate derived
  inputs by availability; integrate simulation with deterministic jobs and reports; and route the
  synthetic proving ground and textbook example through the native path.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` passes at 100%; power is 48/50,
  null size is 7/200 inside [3, 19], all six canaries and replay equivalence pass, and simulate
  output is byte-identical across serial and parallel runs.
- **Metrics:** farm/product +779 and tests +350 from the P18 baseline; server and tools unchanged;
  P18 totals are 2,644/3,000 farm lines and 960/2,500 test lines; budget ok.
- **Next:** nothing admitted.

## 2026-10-01 — Complete P3 free SEC history

- **Why:** approved P3 Phase 0 part 2 after the owner supplied the private SEC contact identity.
- **What:** add fixture-tested, paced, resumable Form 25, insider-transaction, and current CIK-to-
  ticker capture into the isolated free-source store; retain raw responses outside Git; and
  publish the annual SEC/Tiingo/store coverage audit from a disposable consistent store copy.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` reaches 100% with no failures;
  whole-repository Ruff and the metrics budget check also pass.
- **Metrics:** server +0, tools +558, product +495; budget ok.
- **Next:** nothing admitted; Massive remains key-blocked and paid P3 remains spend-blocked.

## 2026-10-02 — Close five generic P18 simulator seams

- **Why:** the orchestrator supplied five hand-computed mismatches covering exit-cost basis,
  entry-session exits, eligible benchmarks, order allocation, and dividends; the pre-fix focused
  reproduction stopped at the missing `Dividend` input.
- **What:** add registered exit-cost and conditional-check choices, point-in-time eligible
  benchmarks, canonical order priority/signals with held-name rejection, and timestamp-gated
  dividends across event, portfolio, benchmark, identity, ledger, and report paths.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` passes at 100%; 62 focused tests,
  whole-repository Ruff, and all six proving-ground canaries pass.
- **Metrics:** server and tools unchanged; product +252 and tests +205; P18 totals are 2,896/3,000
  farm lines and 1,165/2,500 test lines; budget ok.
- **Next:** nothing admitted.

## 2026-10-02 — Validate P15 labels after nightly price re-fetches

- **Why:** the October 2 P15 and P8 reports reproduced `P15 label maturity evidence differs`
  after unchanged nightly price re-fetches replaced the current rows' fetch timestamps.
- **What:** `server/agent_evaluation.py` replays P8/common, P15 scoring, limit, and event labels
  from current values while stored-body hashes stay fatal. `tools/p15_evidence_validation.py`
  centralizes date-bounded SPY sessions and stored price-prefix comparison for common,
  next-session, next-bar, intraday, and missing-next-bar labels, reporting later values as revised
  or unverifiable. `server/p15_price_fetch_attempts.py` validates immutable missing attempt and
  receipt identities without mutable current-row absence. `engine/p15_evaluation.py` makes primary
  and event missing-label maturity date-only. `server/agent_evaluation_reporting.py` has no direct
  filter and inherits the result. Remaining filters are label-writing, fetch-obligation, or
  real-time paths and stay unchanged. Issue revision 8; scoring, books, gates, label writing, and
  written rows do not change.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --dist loadfile` passes at 100%;
  the re-fetch fixture proves unchanged reporting, source-revision reporting, and fatal tampering.
- **Metrics:** server -2, tools +68, product unchanged; budget ok.
- **Next:** recover the October 2 reports and league evidence, then resume P16 W9b.

## 2026-10-02 — Make engine infrastructure observable and contention-tolerant

- **Why:** the owner's P15 revision 9 infrastructure directive and the orchestrator's independent
  audit admitted timing, synchronization recovery, snapshots, and contention work.
- **What:** record per-stage timings; retry one non-fast-forward sync; atomically retain read-only
  snapshots for API and backup fallback; cache expensive status
  projections; reuse observer connections; overlap nightly verification/farm work; and isolate
  evidence-validation exit 75 after league rendering. Registration remains revision 8 here so the
  orchestrator can issue revision 9 once over the merged four-lane tree.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4` reaches 100%: 4,120 pass and 86
  stop only at frozen runtime/registration identity checks intentionally awaiting the merged
  revision 9 registration; the 514 focused tests, whole-repository Ruff, and budget check pass.
- **Metrics:** server +240, tools +384, product +289; budget ok.
- **Next:** orchestrator merges all four infrastructure lanes and issues registration revision 9.

## 2026-10-02 — Bound snapshot writer-lock time

- **Why:** the orchestrator measured 116 seconds of producer-lock hold time for each 5.9GB
  DuckDB snapshot and required a raw-copy fast path plus bounded event publication cadence.
- **What:** when no WAL exists, capture source invariants under producer locks, raw-copy and fsync,
  then release the locks before verifying the copy; retain DuckDB COPY as the WAL-safe fallback.
  Add successful minimum-age skips, remove pre-open publication, and limit event publication to
  once per 120 minutes. Nightly, P15 scoring, and TradingView remain unthrottled.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 tests/test_publish_snapshot.py
  tests/test_backup_database.py tests/test_service_units.py tests/test_drivers.py` passes; the live
  read-only 6,654,537,728-byte store copied, fsynced, and verified in 51.213 seconds with equal
  invariants, and the temporary copy was removed.
- **Metrics:** server and product unchanged; tools +74; budget ok.
- **Next:** orchestrator merges the four infrastructure lanes and issues registration revision 9.

## 2026-10-02 — Remove walk-forward queue and scratch bottlenecks

- **Why:** the orchestrator reproduced same-priority batch barriers in the 3.07-hour Sunday
  drain and 18 unheld killed-worker scratch directories consuming 14,652,368,972 bytes.
- **What:** replace barriered batches with an eight-slot priority-ordered rolling pool that keeps
  the writer and drain-budget boundaries. Share one read-only walk-forward input store per run,
  retain private writable overlays, convert worker SIGTERM to cleanup, and sweep only unheld
  orphan directories. Remove the 18 verified unheld production orphans.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_walkforward_scratch.py
  tests/test_result_provenance.py tests/test_queue_runner.py` passes all 61 tests; two-book,
  two-fold store-copy outputs match with scratch 871,477,215 → 445,247,500 bytes.
- **Metrics:** server and tools unchanged; product +336 lines; budget ok.
- **Next:** nothing admitted; P15 revision 9 must bind the two changed registered files.

## 2026-10-02 — Bound nightly network collection

- **Why:** the owner's October 2 engine-bottleneck audit measured serial price verification and
  full-universe earnings refreshes dominating the 44.5-minute nightly.
- **What:** pace four price-verifier workers through one global 0.4-second limiter; refresh only
  unknown, near-term, or seven-day-stale earnings names outside the Monday full pass; and collect
  two to four completed sessions per caught-up TradingView request without raising its rate or
  chunk cap. Keep the measured 200-name EOD batches after larger/session-reuse probes regressed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py::test_p15_registered_file_hashes_match_checkout` passes at 100%;
  copy probes preserved every fact while verifier time fell 515.2→100.1 seconds and the bounded
  earnings night selected 1,229/2,848 names.
- **Metrics:** product +261 and tests +330; snapshot reconciliation also records server -2 and
  tools +69 from the preceding revision; budget ok.
- **Next:** the orchestrator folds the three changed registered modules into P15 revision 9.

## 2026-10-02 — Issue P15 registration revision 9

- **Why:** the orchestrator approved one infrastructure-only registration after the four lanes
  merged, and removal of the unmeasured DuckDB caps restored the XS runtime contract.
- **What:** issue revision 9 over the merged timing, sync, snapshot, reporting, cache, observer,
  verify/farm, intraday, queue/scratch, price, earnings, and TradingView work. Rebind the complete
  P15 dependency closure without changing scoring, books, gates, labels, registered values, or
  written rows; update the P15 W8 and P16 W0 progress records.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4` passes at 100%; whole-repository
  Ruff passes and the metrics budget is `ok`.
- **Metrics:** server and tools unchanged; product -55 lines; budget ok.
- **Next:** deploy revision 9 and resume P16 W9b.

## 2026-10-02 — Make shared study simulation columnar

- **Why:** the orchestrator-approved P18 performance follow-up and two generic native-port
  evaluation seams.
- **What:** add the realistic benchmark and immutable ticker/session numpy panel; share it by
  fork and replace whole-market MDV, history and allocation scans. Add opt-in unevaluable
  window-end and complete-path rules while retaining default output bytes.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%;
  295 captured pre-existing JSON outputs (53,391,323 bytes) also match byte for byte.
- **Metrics:** server and tools unchanged; product +542 lines; P18 is 3,438/3,600 farm lines.
- **Next:** nothing admitted.

## 2026-10-02 — Start the free Massive small-stock minute archive

- **Why:** P3 Phase 0 part 4, directed by the owner and technically specified by the orchestrator.
- **What:** freeze a 3,302-ticker universe from the completed grouped-daily MDV60 history; add
  paginated minute parsing, NYSE session tags, content-addressed resume, isolated storage, and a
  window-aware background runner. Make grouped-daily and minute requests share one process-safe
  13-second key limiter, with fixture coverage for the existing daily job.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%;
  whole-repository Ruff and the published metrics budget also pass.
- **Metrics:** server unchanged; tools +361, product +344, tests +244 lines; budget ok.
- **Next:** the orchestrator reviews checkpoint minute-1 while the resumable capture runs.

## 2026-10-02 — Reject the frozen Kaggle archive after census

- **Why:** P3 Phase 0's orchestrator-directed frozen-archive census and conditional 30% ingest
  gate.
- **What:** retain the exact CC0 ZIP and full per-ticker census outside Git; add the offline
  parser, deterministic Tiingo/Form 25 comparison, ticker-risk flags, split-basis checks, and
  public census report. Coverage failed the gate, so no loader or database was created.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%;
  whole-repository Ruff and the published metrics budget also pass.
- **Metrics:** server unchanged; tools +49; product +554 lines; budget ok.
- **Next:** nothing admitted; keep the archive out of research and continue existing P3 capture.

## 2026-10-03 — Issue P15 registration revision 10

- **Why:** the orchestrator-directed revision 10; the pre-fix reproduction rejected the latest
  2026-10-02 nightly book-equity row as `P15 book evidence has orphan rows`.
- **What:** treat exactly one latest equity date after each book's processed window as pending;
  keep older gaps and multiple pending dates fatal. Surface the pending count and dates in the
  report and status API, rebind the registered closure, and update the P15/P16 progress rows.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%.
- **Metrics:** server +6, tools +17, product unchanged; budget ok.
- **Next:** resume P16 W9b.

## 2026-10-03 — Restore the CI security-lint gate

- **Why:** public Actions run 37091722960 reproduced an S101 failure at
  `farm/study/data.py:300` after the revision 10 push.
- **What:** replace the optimization-sensitive panel-presence assertion with the same explicit
  `KeyError` used by the view's missing-coordinate contract.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%.
- **Metrics:** server and tools unchanged; product +1; budget ok.
- **Next:** resume P16 W9b.
## 2026-10-02 — Build the offline SEC bulk checkpoint

- **Why:** P3 Phase 0 part 4 admits the owner's requested free SEC nightly bulk fundamentals and
  earnings timestamps under the orchestrator's bounded technical contract.
- **What:** add isolated Companyfacts and Submissions parsers, an acceptance-time as-of macro,
  retained restatements and item 2.02 events. Add a single-connection, paced, resumable archive
  client and read-only CIK ticker attachment; live downloads remain unopened until 20:15 UTC.
- **Evidence:** `.venv/bin/python -m pytest tests/test_free_sec_bulk.py -q -W error -n 0` passes
  all 5 fixture tests; focused Ruff passes.
- **Metrics:** server unchanged; tools +400; product +595 lines; budget ok.
- **Next:** verify both bulk URLs by HEAD and resume the live capture in the first permitted window.

## 2026-10-02 — Resume SEC bulk through the quiet-window boundary

- **Why:** P3 Phase 0 part 4 requires live archive compatibility and resumable capture in the
  registered network window.
- **What:** accept empty issuer histories and legacy SEC item text while keeping exact `2.02`
  filtering; vectorize the 22.1 million-row Submissions load and require identity encoding for
  byte-range resume. Cache and load every older page, then retain the Companyfacts partial at the
  21:45 UTC boundary.
- **Evidence:** a read-only query reports 987,283 Submissions members, all 5,387 older pages loaded,
  18,788,867 unique accessions, 421,723 earnings events, and zero facts pending Companyfacts resume.
- **Metrics:** server unchanged; tools +5; product +46 lines; budget ok.
- **Next:** resume the remaining Companyfacts bytes at 23:30 UTC, load facts, audit, and run gates.

## 2026-10-03 — Complete the SEC bulk point-in-time audit

- **Why:** P3 Phase 0 part 4 required both nightly SEC archives, referenced older submissions,
  point-in-time fundamentals and earnings timestamps, and the dated coverage audit.
- **What:** complete the resumable Companyfacts load, accepting only observed SEC placeholders and
  fiscal-year sentinels without weakening identity checks. Publish annual fact/company/event counts,
  ticker match rates and read-only engine-earnings overlap in the P3 audit.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%;
  whole-repository `.venv/bin/ruff check .` reports `All checks passed!`.
- **Metrics:** server unchanged; tools +3; product +10 lines; budget ok.
- **Next:** nothing admitted; paid P3 data remains spend-blocked.

## 2026-10-03 — Measure SEC coverage from the engine calendar

- **Why:** the orchestrator accepted the SEC bulk work in principle but found the all-SEC-event
  overlap denominator misleading for the engine's current-name, recent-window earnings table.
- **What:** deduplicate engine ticker/dates inside the mapped SEC Submissions window and report
  same-ticker item 2.02 coverage at ±1 and ±3 days. Add a deterministic 30-miss sample with five
  aggregate reason categories and no published ticker identities; retain the event-first measure
  only as an explicitly labelled source diagnostic.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 4 --dist loadfile` passes at 100%;
  whole-repository `.venv/bin/ruff check .` reports `All checks passed!`.
- **Metrics:** server unchanged; tools +20; product +73 lines; budget ok.
- **Next:** nothing admitted; paid P3 data remains spend-blocked.

## 2026-10-03 — Implement the offline market-data auditor

- **Why:** owner-directed P19 adds independent coverage measurement required by the backtest standard.
- **What:** typed raw snapshots and frozen NYSE rules retain omitted securities, uncertain reference
  eligibility, unavailable inputs and complete finding totals. Separate JSON/Markdown reports and
  a fictional native-evaluator example expose a positive-to-negative result reversal.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -o addopts='' tests/test_study_*.py tests/test_operating_contract.py`
  → 123 passed; the runnable diagnostic independently reproduces +0.9740742% vs -2.0510404%.
- **Metrics:** server/tools unchanged; new farm/test code only; budget passes. Large-scale memory unmeasured.
- **Next:** publish the branch and verify full Linux CI before closing P19.

## 2026-10-03 — Verify and close the offline auditor slice

- **Why:** P19 requires independent acceptance and full Linux CI before closure.
- **What:** correct the missing plan-index link found by CI and close the offline slice.
  Real-data adapters, revision/action tracing, visual export and production-scale performance
  remain separate work; the evaluator and live paths are unchanged.
- **Evidence:** `gh run view 37106130373` reports successful complete-suite jobs in UTC and
  Asia/Singapore plus UI build; all 45 new auditor cases also pass locally.
- **Metrics:** server/tools/product code unchanged by closure; snapshot republished with budget ok.
- **Next:** merge the verified closure; no additional P19 implementation admitted.

## 2026-10-05 — Reproduce engine and dashboard review defects

- **Why:** owner-authorized P20 review covers existing engine and dashboard correctness.
- **What:** reproduce same-chunk duplicate-price overwrite, terminal-zero report failure, and
  the API rejecting the frozen monitor's real accumulating XS payload. Host inspection confirms
  the same missing observation field rejects the current two-session report.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_study_spec_data.py tests/test_study_runner_report.py tests/test_xs_forward_status.py`
  fails five new regressions: two duplicate chunk sizes, two zero-exit sides and the real monitor projection.
- **Metrics:** server/tools/product unchanged before fixes; budget passes.
- **Next:** correct generic normalization, reporting and the API projection without changing frozen evidence.

## 2026-10-05 — Fix and independently verify the engine and paper dashboard

- **Why:** the reproduced defects and the owner's P20 review admit these bounded corrections.
- **What:** reject duplicate panel coordinates, preserve terminal-zero return cross-checks,
  project valid accumulating/early-kill forward evidence, and make every header alert reachable.
  Reconcile setup, architecture, operating guidance and the current registration revision.
- **Evidence:** full Linux `.venv/bin/python -m pytest -q -W error -n 8` exits 0 (4,309 cases).
  Independent review passes 83 focused cases, 54 UI tests and browser checks at 390/1280px;
  the production build and Ruff pass. macOS cannot run Linux operational assertions.
- **Metrics:** published snapshot passes the budget; source changes remain below the commit cap.
- **Next:** publish, verify CI and inspect the deployed read-only API and dashboard.

## 2026-10-05 — Close verified engine and dashboard review

- **Why:** P20 requires independent acceptance, publication and production verification.
- **What:** close the review after deployment; preserve genuine source-quality and cohort warnings.
- **Evidence:** `gh run view 37283503856` reports successful UTC/Singapore tests and UI build.
  Deployed `/meta` shows accumulating two-session XS evidence; four browser routes return 200
  without JavaScript errors, and the 390px status region stays within the viewport.
- **Metrics:** code unchanged; metrics budget passes.
- **Next:** nothing further admitted by P20; existing collection and revalidation continue.


## 2026-10-05 — Admit operational issue closure and separate-account proof

- **Why:** Owner approved P21 after P20 and requested separate saved state for every strategy account.
- **What:** Record operational fixes, source-preserving complexity work and account isolation as one bounded plan.
  Verifier regressions reproduce truncated discrepancies, accepted missing/wrong symbols and nonfinite prices.
- **Evidence:** `pytest -q tests/test_verify_prices.py` before fixes: three new regressions fail; existing checks pass.
- **Metrics:** Baseline captured; 32 advisory server/tools complexity findings.
- **Next:** Correct verification evidence and recoverable provider requests, then independent acceptance.

## 2026-10-05 — Retain source evidence and recover transient capture requests

- **Why:** P21; corrected reproduction confirms truncation hides four disagreeing securities and invalid source identity/numbers pass parsing.
- **What:** Keep every discrepancy/name and exact HTTP receipts; publish immutable verified evidence before the current summary.
  Retry transient minute requests three times with shared pacing/window checks. Preserve failures via evidence-bound queue dispositions.
- **Evidence:** `pytest -q tests/test_verify_prices.py tests/test_free_massive_minute.py tests/test_job_resolutions.py tests/test_queue_monitor.py -W error`: 43 passed.
- **Metrics:** Pending final snapshot; registered source changes await the next properly rehearsed revision.
- **Next:** Engine-owned independent paper accounts and remaining focused infrastructure refactors.

## 2026-10-05 — Separate engine-owned paper accounts and complete history fallback

- **Why:** P21; owner requested independently saved strategy accounts with USD 10k/50k/100k tiers and private-alpha/engine separation.
- **What:** Bind immutable generic account specifications; accept only timely prospective stock/ETF requests into existing next-open accounting.
  Reject unsupported instruments, cross-account spending, stale requests and re-funding; prove parallel strategy/account isolation.
  A failed maximum-history fetch gets an explicit-date fallback only after provider identity and every completed listing session validate.
- **Evidence:** `pytest -q tests/test_collect.py tests/test_paper_accounts.py -W error`: 34 passed.
- **Metrics:** Pending final snapshot; no existing portfolio balance or frozen private request changed.
- **Next:** Finish behavior-preserving source extraction and bind the reviewed registration revision.

## 2026-10-05 — Split registered evidence checks without changing their decisions

- **Why:** P21's explicit complexity scope; eleven advisory findings in the registered evidence path and capture tools.
- **What:** Extract trace/sample/receipt/book validation, pre-open replay/commit, scoring context/sample replay and provider pacing/stream helpers.
  Keep checks, ordering, errors and side effects intact; no model, threshold or frozen rule changes.
- **Evidence:** Focused scoring/pre-open/evaluation/collector suite: 127 passed; capture/tools/evaluation suite: 85 passed. Owned paths have zero C90 findings at ten.
- **Metrics:** The 21 remaining findings are confined to the separately owned P16 extraction.
- **Next:** Register the reviewed source revision and run one complete supported-Linux verification after independent review.

## 2026-10-05 — Preserve request pacing after a delayed worker wakes

- **Why:** P21 rehearsal reproduced the existing verifier concurrency regression: requests started less than the reserved interval apart.
- **What:** Hold the reservation lock across the wait and anchor the next slot to actual wake time; refuse a wake beyond the deadline.
  Retain exact in-memory store bars in the immutable verification receipt alongside raw provider bytes.
- **Evidence:** Focused verifier regression now includes deterministic oversleep and deadline tests; the previously failing concurrent check passes.
- **Metrics:** No threshold or comparison tolerance changed.
- **Next:** Refresh the prepared source registration after this corrected pacing implementation.

## 2026-10-05 — Bind the corrected operating path as source revision 11

- **Why:** P21 requires real source identity changes to use the existing registration contract, not a hash-gate bypass.
- **What:** Register the committed verifier, full-history collector and behavior-preserving evidence/capture source changes.
  Revision 10 remains reproducible in Git; all policy constants, activation clock, scoring, books, gates, labels and schedules remain equal.
- **Evidence:** `pytest` registration/evaluation/pre-open/scoring/verifier/account fixture rehearsal: 99 passed; no runtime model call.
- **Metrics:** Updated metrics snapshot passes the existing hygiene budget.
- **Next:** Independent review, remaining inactive P16 source amendment and one complete Linux suite before deployment.

## 2026-10-05 — Finish inactive research extraction and preserve queue projection parity

- **Why:** P21; the independent worker completed twenty-one P16 advisory findings and found one source-bound inactive adapter.
- **What:** Merge reviewed helper extraction; amend only the inactive adapter's registered source digest and enclosing hashes.
  Extend the board's exact queue schema to the two evidence-backed dispositions without accepting arbitrary reasons.
- **Evidence:** P16 worker: 144 focused tests; original/refactored adapter: same nine transcript cases. Integrated registration/account/queue suite: 35 passed; UI: 55 passed.
- **Metrics:** `ruff check --select C90 server tools`: all checks passed at threshold ten; no new exemption.
- **Next:** Independent functional review and complete supported-host validation before deployment.

## 2026-10-05 — Resolve independent accounting and source-evidence findings

- **Why:** P21 review reproduced intake marking an unfinished nightly as complete; nonfinite prices could agree and seven malformed-response cases lost receipts.
- **What:** Defer initial marks to the league and require completed active-book accounting before later intake.
  Reject invalid history/comparison values, retain malformed source bodies as refusals, and use a host-neutral receipt reference.
  Label queue completion as operator-attested; matching request parameters alone cannot prove resumable chunk coverage.
- **Evidence:** Account/collector/verifier suite: 61 passed, including real bootstrap/next-open league steps and malformed-response continuity; queue: 26 passed; UI: 55 passed.
- **Metrics:** Pending final snapshot; registered constants, balances and frozen strategies are unchanged.
- **Next:** Refresh the prepared source identity, independent acceptance and complete supported-host verification.

## 2026-10-05 — Bind reviewed source corrections and final fixture evidence

- **Why:** P21; independent review corrected accounting and source refusal behavior before revision 11 deployment.
- **What:** Refresh the prepared registration's exact source commit and collector/verifier digests; retain every registered policy constant.
  Document the corrected activation checkpoint and operator-attested queue completion semantics.
- **Evidence:** Registration/evaluation/pre-open/scoring/verifier/account and operating-contract rehearsal: 127 passed; required lint and C90 checks pass.
- **Metrics:** Budget passed; since the previous snapshot, server/tools unchanged, product +48, tests +122.
- **Next:** Independent acceptance and one complete supported-Linux suite, then orchestrated live verification.

## 2026-10-05 — Preserve frozen collector and correct supported-host review failures

- **Why:** P21 Linux suite reproduced 41 frozen collector hash failures, two documentation defects and an uncaught optional provider error.
  Backup review also reproduces fingerprinting a descriptor symlink instead of its opened directory.
- **What:** Restore the exact frozen collector and move complete-history recovery to explicit insert-only maintenance with reused-ticker refusal.
  Degrade TradingView cross-check source errors to missing evidence; remove an unintended network call from the observer fixture.
  Retain explicit provider symbol/series refusals before reporting unavailability, without waiting for a generic timeout.
  Restore the log tail marker and direct plan index; fingerprint the real backup root while preserving child symlink checks.
- **Evidence:** XS/collector/history recovery/observer/docs suite: 106 passed; provider/observer/archive suite: 42 passed; backup root regression fails before and passes after.
- **Metrics:** Pending final snapshot; no frozen strategy, signal boundary or stored price is rewritten.
- **Next:** Independent sidecar and backup review, final registered dependency refresh and supported-host verification.

## 2026-10-05 — Bind supported-host corrections without changing frozen records

- **Why:** P21 requires the final operational corrections to pass the existing registered source contract before deployment.
- **What:** Refresh the prepared revision 11 dependency map for restored collection, explicit provider refusals and backup directory identity.
  Update its exact revision-reason assertion to describe these reviewed corrections; self-hash and dependency gates remain intact.
- **Evidence:** Final source rehearsal: 120 passing cases; refreshed registration suite: five passed. All required lint and C90 checks pass.
- **Metrics:** Budget passed; since the preceding snapshot, server +9, tools +2, product +78, tests +143.
- **Next:** Complete Linux verification and live maintenance checks under the orchestrator.

## 2026-10-05 — Complete the CI lint checks for capture pacing

- **Why:** P21 publication checks found one mandatory RET504 violation after the supported-Linux suite passed all 4,381 tests.
- **What:** Return the pacing helper's monotonic timestamp directly, preserving the same call order and value.
  The helper is outside P15's registered source closure; its existing revision, dependency map and source commit remain valid.
- **Evidence:** Source/minute-capture/registration tests: 41 passed. All CI Ruff selectors pass: default, C90, PLW2901, RET504 and S101.
- **Metrics:** Budget passed; tools -1 line, server/product/tests unchanged.
- **Next:** Observe both timezone CI runs before deployment.

## 2026-10-06 — Accept the provider's lazy history metadata

- **Why:** P21 live history recovery refused valid ETF identity: the installed provider returns a Mapping wrapper, not a dict.
  The new regression using the actual provider wrapper reproduces the same refusal before the correction.
- **What:** Accept mapping metadata while preserving every security, currency, coverage and overlap check.
  Read only required keys; do not materialize unrelated lazy intraday fields or change the frozen collector.
- **Evidence:** Actual provider-wrapper regression failed before the fix; all 24 history-recovery/registration checks pass after it.
- **Metrics:** Budget passed; engine +1 line and tests +13, frozen collector and registered source bindings unchanged.
- **Next:** Verify the explicit history recovery and current-source research refresh.

## 2026-10-06 — Reconcile current deployment documentation

- **Why:** P21 live acceptance verified revision 11, while current status pages still named revision 10.
- **What:** Update the current README, operating state and plan progress to the deployed revision.
  Retain historical revision records and distinguish earlier validation fixes from the current source amendment.
- **Evidence:** Live API/UI health checks passed; all 135 registered source bindings verified. Published CI passed both timezones and UI at the deployed source.
- **Metrics:** Runtime unchanged; documentation only.
- **Next:** Complete the isolated walk-forward refresh and off-host archive/restore verification.

## 2026-10-06 — Admit the complete verifier snapshot in the board

- **Why:** P21 browser acceptance reproduces valid 1,835,568-byte metadata rejected by the generic 1 MiB reader; the board hides nightly, liquidity and price evidence.
- **What:** Give only the aggregate metadata snapshot an 8 MiB ceiling, using the same stable-file reader and strict JSON decoder.
  Keep shared file limits, duplicate-key/nonfinite/nesting checks and registered source dependencies unchanged.
- **Evidence:** The real-snapshot assertion fails before and passes after correction; 96 supported-Linux metadata/file/registration tests pass. Independent Python 3.12 strict-loader tests also pass.
- **Metrics:** Budget passed; server +5 lines, tests +36. Engine/farm/sim sources and the active walk-forward identity remain unchanged.
- **Next:** Independent review, CI and real-browser acceptance, then final archive and research acceptance.

## 2026-10-06 — Project complete verifier evidence through the existing board limit

- **Why:** P21 real-payload validation reproduces the next integration mismatch: the monitor expects exactly 20 truncated rows and rejects the complete 84-row verifier evidence.
- **What:** Validate either retained legacy summaries or complete producer details, then publish only the existing worst-20 view with explicit total/truncation fields.
  Validate every supplied row, full ticker counts and material counts before truncating; source receipts and policies stay unchanged.
- **Evidence:** Real metadata fails before and passes after correction (84 total, 45 material, 20 displayed); 92 focused tests pass. Independent replay and all registered bindings pass.
- **Metrics:** Budget and unchanged C90 threshold pass; server +2 lines, tests +42. No research-runtime or registered-source identity changes.
- **Next:** Validate and deploy the two complete-evidence reader corrections, then finish operational acceptance.

## 2026-10-06 — Admit the complete-metadata recovery correction

- **Why:** The actual daily backup refused `data/_meta.json` above 1,048,576 bytes and used its existing locked-copy fallback.
- **What:** Admit an 8 MiB limit for this exact metadata artifact in copying and verification; retain other caps.
  P15 revision 12 must bind the correction before deployment; policy, books, clocks and schedules stay unchanged.
- **Evidence:** The saved backup command exited zero with the refusal and fallback method recorded; this is not verified-bundle proof.
- **Metrics:** Extend P21 to 21 logical commits: source correction first, then its exact registration; existing line limits stay fixed.
- **Next:** Independently review the correction, bind its committed source, rehearse revision 12 and finish recovery acceptance.

## 2026-10-06 — Close the operational and account-isolation review

- **Why:** P21's implementation, independent review and final recovery gates are complete.
- **What:** Record engine-owned accounts, the 18/18 public walk-forward refresh and verified private recovery.
  Reconcile implemented intake with still-gated strategy activation; preserve P15 and frozen source authority.
- **Evidence:** Earlier implementation CI passed both timezones and UI; revision 12 was rehearsed, and recovery receipts passed independent acceptance.
- **Metrics:** Research runtime unchanged; revision 12 binds the reviewed backup source correction.
- **Next:** Nothing further admitted by P21; P15 continues its registered evidence collection.

## 2026-10-06 — Correct the vulnerable UI source-map dependency

- **Why:** CI run 37421970021 failed its mandatory production-dependency audit on source-map-js 1.2.1 (GHSA-68fv-2mgg-jv7q).
- **What:** Update only source-map-js 1.2.1 to 1.2.2 in the lockfile; UI behavior and trading source are unchanged.
- **Evidence:** Public-registry audit changed from one high-severity finding to zero; all 55 UI tests and the production build pass on Node 20.
- **Metrics:** Production source LOC and the 135 registered bindings are unchanged.
- **Next:** Verify exact-commit CI, then install the fixed dependency and restart the production dashboard.

## 2026-10-06 — Add the engine-v2 identity foundation

- **Why:** Active P22 L0 foundation plan: additive schema, monotonic order ids, instrument identities and order lifecycle.
- **What:** Add the v2 side tables and portfolio metadata without changing positional legacy ledger tables.
  Bootstrap a persistent order sequence, canonicalise OCC contracts, and define order states and receipt cutoffs.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_schema_v2.py tests/test_instruments.py tests/test_order_types.py` — 16 passed.
- **Metrics:** server/tools unchanged; product +453 lines; budget clean.
- **Next:** Implement the effective-dated cost registry and its authoritative worked examples.

## 2026-10-06 — Implement effective-dated dollar costs

- **Why:** P22 L0 and ruling R10 require the verified IBKR schedule and exact worked examples.
- **What:** Add immutable cost-profile identities, unrounded fee components, half-up totals, and dated SEC/TAF/margin rates.
  Keep baseline fees zero and expose the same engine profile through the generic study layer.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_costs_ibkr.py` — 11 passed, including all eight verified examples.
- **Metrics:** server/tools unchanged; product +423 lines; budget clean.
- **Next:** Build side-aware fill accounting, cash events, lots, and deterministic replay phases.

## 2026-10-06 — Centralise side-aware ledger replay

- **Why:** P22 L0 requires one fill/cash writer and phase-ordered reconstruction with exact legacy compatibility.
- **What:** Delegate portfolio fills and rebuilds to a buy/sell/short/cover ledger with FIFO lots and dollar fees.
  Replay dividends, settlements, fills and cash events in phases 0–3; short dividends are signed debits.
- **Evidence:** The 99-test L0/portfolio/settlement/regression set passes, including exact multi-day legacy replay and short-cover accounting.
- **Metrics:** server/tools unchanged; product +228 lines; budget clean.
- **Next:** Run repository-wide acceptance, package cross-lane compatibility patches, and publish the final metrics snapshot.

## 2026-10-06 — Stamp fill model v5

- **Why:** P22 L0 acceptance requires the new ledger semantics to carry a distinct fill-model identity.
- **What:** Define v5 in the execution layer and re-export it through the existing portfolio interface.
  The baseline slippage coefficients and legacy zero-fee arithmetic remain unchanged.
- **Evidence:** All 34 claimed L0 tests pass; repository-wide `ruff check .` passes.
- **Metrics:** server/tools unchanged; product +2 lines; budget clean.
- **Next:** L3 must migrate frozen runtime identities and apply the supplied compatibility patch before the full suite can pass.

## 2026-10-06 — Preserve first-seen prices and refresh account names

- **Why:** P22 L4 sections 6.3 and 8 admit bitemporal prices and daily held,
  pending and watched-name freshness; the frozen collector must retain its bytes.
- **What:** Preserve `first_fetched_at` across price corrections and add the isolated
  account-watch table/universe collector for L3 to call before the frozen collector.
- **Evidence:** On a 21,011,171-row snapshot copy, seven paired 1,000-row repeats measured
  `ON CONFLICT` at 6.976 ms versus 6.529 ms for `INSERT OR REPLACE` (6.84% slower, under 20%).
- **Metrics:** engine +158, product +158, tests +127; server/tools unchanged; budget ok.
- **Next:** add Massive split capture and the adjusted grouped-daily view.

## 2026-10-06 — Re-adjust grouped bars for later splits

- **Why:** P22 L4 sections 6.2 and 8 admit daily Massive split capture and an
  as-fetched adjustment view without re-fetching the rolling daily archive.
- **What:** Store first-seen split facts, retain exact reference responses and apply
  only splits whose ex-date follows both the bar date and its fetch date.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_free_splits.py
  tests/test_free_sources.py` passes all 29 recorded-fixture and existing cases.
- **Metrics:** engine +107, tools +117, product +107, tests +102; server unchanged; budget ok.
- **Next:** add the bounded Massive contracts and option-daily capture.

## 2026-10-06 — Capture a bounded free options dataset

- **Why:** P22 L4 sections 6.4 and 8 admit options reference and daily aggregates
  for a frozen free universe, with no execution authority or live-network tests.
- **What:** Add manifest-bounded contract snapshots, daily bars, verified raw receipts
  and shared-limiter capture. The permitted temp-DB SPY smoke loaded 748 contracts in one page.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_free_massive_options.py
  tests/test_free_splits.py tests/test_free_sources.py tests/test_free_massive_minute.py`: 42 passed.
- **Metrics:** server unchanged, tools +379, product/engine +286, tests +125, docs +14; budget ok.
- **Next:** register the options and account-settle systemd units without installing them.

## 2026-10-06 — Register data and late-settlement timers

- **Why:** P22 L4 section 8 requires the options 11:35 UTC job and account late-settle
  07:45/11:55 UTC jobs to ship through automation without installing or starting them.
- **What:** Add the four hardened oneshot/timer units, register both timers for autostart,
  and accept an explicit read-only `--audit` mode. No host automation state changed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_install_automation.py`
  passes all 50 cases; systemd verification passes and audit lists all four new units.
- **Metrics:** server/product unchanged, tools +12, tests +26; budget ok.
- **Next:** run the complete L4 acceptance and repository gates.

## 2026-10-06 — Keep bitemporal upsert compatible with legacy fixtures

- **Why:** the required full suite reproduced `upsert_prices` refusing a minimal
  pre-migration prices fixture that intentionally omits `first_fetched_at`.
- **What:** Use the point-in-time conflict path directly on current stores and fall
  back to the former write only after confirming the optional column is absent.
- **Evidence:** On the 21,011,171-row snapshot copy, seven paired 1,000-row repeats
  measured 21.735 ms versus 20.197 ms today (7.62% slower, under the 20% limit).
- **Metrics:** server/tools unchanged, product/engine +14, tests +15; budget ok.
- **Next:** hand positional whole-row writers to their owning integration lane, then close gates.

## 2026-10-06 — Hand L4 integration-bound gates to their owners

- **Why:** P22 requires the complete suite, while L4 may not edit the frozen
  forward monitors, replay writer, nightly driver or their tests.
- **What:** All claimed acceptance is green. Two format patches cover the L3
  nightly call and six positional price writers; L3 must rebind E1/sector/XS after all merges.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,306 passed, 104 integration-bound failures, 5 deselected.
- **Metrics:** server/tools/product unchanged since the prior entry; budget ok.
- **Next:** orchestrator applies the two handoff patches and L3 issues the merged runtime contracts.

## 2026-10-06 — Keep account freshness fail-soft

- **Why:** P22 L3 owns the nightly handoff; the orchestrator reproduced three driver
  expectation failures and ruled that an account-freshness lock timeout cannot abort trading.
- **What:** The account freshness stage now warns and continues, while the P15 collector
  remains fatal; driver expectations cover the added stage and both failure semantics.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_drivers.py` — 28 passed.
- **Metrics:** server/tools/product unchanged; engine +1 and tests +13; budget ok.
- **Next:** implement L3 routing, monotonic ids, fees, rerun protection, and public reports.

## 2026-10-06 — Route books through costed engine ledgers

- **Why:** active P22 L3 sections 2.4, 2.5, 4, and 5 require one routed fill path,
  monotonic ids, protected reruns, dollar fees, break-aware reports, and public isolation.
- **What:** League, P15, and P16 now allocate sequence ids and charge effective-dated
  profiles through the shared ledger. Reruns preserve every attributed order and fee sidecar.
  Lazy account accrual/settle/halt phases keep their specified order before L1/L2 merge.
  Public Markdown, CSV, and API projections exclude private side-table accounts.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_league_v2.py` — 6 passed.
- **Metrics:** server +22, tools unchanged, product +396; tests +218; budget ok.
- **Next:** add the one-shot D0 migration and restart every book evaluation clock.

## 2026-10-06 — Restart book clocks at the commission break

- **Why:** P22 section 4 requires a one-shot D0 migration and restarts every
  book-comparison clock without rewriting its frozen pre-break evidence.
- **What:** Add the parameterized migration, R13 side-table routing, break rows,
  sequence reservation, and lazy L4 first-fetch backfill. It refuses repeats and any
  D0-or-later equity. P15, P8, sector, and XS metrics now start at their common break;
  the frozen forward prefixes remain validated and their reports disclose the restart.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_migrate_cost_profiles.py
  tests/test_book_breaks.py tests/test_p15_evaluation.py` — 36 passed.
- **Metrics:** server unchanged, tools +144, product +68; tests +342; budget ok.
- **Next:** reconcile P22's product/scope/blueprint/plan documents, then run lane gates.

## 2026-10-06 — Record the engine-v2 account decisions

- **Why:** P22 R9 and L3 require the dated owner decisions, architecture, scope and
  two-phase frozen-contract closure to be durable before integration.
- **What:** Product now records executor/ledger ownership, costs, fills, PDT, shorts,
  halts, options refusal, versioning and monthly review. Scope and blueprint describe the
  R13 side table and public/private boundary; the active plan separates Phase A from the
  post-merge rehearsal and explicit E1/sector/XS/walk-forward/P15 revisions in Phase B.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_operating_contract.py
  tests/test_documentation_integrity.py` — 16 passed.
- **Metrics:** server/tools/product unchanged; documentation +76 lines; budget ok.
- **Next:** run focused gates, Ruff, the baseline-diffed full suite, and the metrics check.

## 2026-10-06 — Preserve pre-D0 replay compatibility

- **Why:** the required full suite reproduced four failures outside the 185-node
  frozen-identity baseline: nightly parsing, legacy-id reuse and two P16 replay cases.
- **What:** Keep the frozen ten-column standings table and publish break metrics beside it;
  skip legacy ids until R13 lands; clear position lots before P15 replay; and avoid writing
  zero-fee sidecars for baseline fills. All four reproductions pass.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --tb=no --deselect
  tests/test_p15_registration.py` — 4,276 passed; the 182 failures exactly equal the
  185-node P22 base list minus the three repaired driver nodes.
- **Metrics:** server/tools unchanged, product +23; tests unchanged; budget ok.
- **Next:** publish the metrics snapshot and hand Phase A to the orchestrator.

## 2026-10-06 — Publish P22 L3 Phase A metrics

- **Why:** the active P22 plan and operating contract require a budget-checked metrics
  snapshot after the lane's focused and baseline-diffed full-suite gates.
- **What:** Publish the 2026-10-06 repository snapshot after Phase A; no runtime,
  registered policy, live state or data producer changed in this closure step.
- **Evidence:** `.venv/bin/python -m tools.metrics_snapshot --check-budget` — snapshot
  published with `budget.ok=true` and no violations.
- **Metrics:** server/tools/product unchanged; budget ok.
- **Next:** await the orchestrator's Phase B signal and refreshed P22 base.
## 2026-10-06 — Add account auction and intraday fill attempts

- **Why:** active P22 L1 requires opening/closing auctions and deferred minute-bar
  market/limit execution without changing the legacy next-open fill path.
- **What:** Add point-in-time daily/minute source readers, inclusive auction cutoffs,
  next-minute market pricing, one-tick limit touches, and v2 fill provenance fields.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_fills.py
  tests/test_fills_v2.py tests/test_p15_fills.py`: 35 passed.
- **Metrics:** server/tools/product unchanged; sim and tests grew within the P22 plan budget.
- **Next:** implement short locates, borrow/buy-ins, Reg T and both R10 settings.

## 2026-10-06 — Add short and margin controls

- **Why:** P22 L1 and R10 require point-in-time locates, borrow/buy-ins, Reg T,
  margin calls, and selectable legacy or 2026 intraday day-trading rules.
- **What:** Add conservative locate classification, threshold-list buy-ins, financing
  cash events, Reg T state/reductions, fractional-lot day trades, and the R13 accessor shim.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_shorts.py
  tests/test_margin.py tests/test_ledger.py tests/test_costs_ibkr.py`: 33 passed.
- **Metrics:** server/tools/product unchanged; sim and tests grew within the P22 plan budget.
- **Next:** settle account orders with aggregate liquidity, fees, contingencies and late marks.

## 2026-10-06 — Settle account sessions through the common ledger

- **Why:** P22 L1 requires one ordered settlement pass for account auctions,
  deferred intraday orders, aggregate liquidity, contingencies and late bars.
- **What:** Route due account orders through locates, R10, Reg T, gross/liquidity
  caps, L0 fees and ledger; persist fill provenance and restate only late-filled accounts.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_accounts_settle.py
  tests/test_fills_v2.py tests/test_shorts.py tests/test_margin.py tests/test_ledger.py
  tests/test_costs_ibkr.py`: 52 passed.
- **Metrics:** server/tools/product unchanged; engine/sim/tests remain within the P22 budget.
- **Next:** run the lane acceptance set, full-suite failure diff, ruff and metrics publication.

## 2026-10-06 — Close P22 L1 execution gates

- **Why:** P22 L1 is done when focused acceptance, ruff, metrics and the full
  repository suite add no failure beyond the R12 base list.
- **What:** Confirm all L1 fills, shorts, margin, R10 and settlement tests; retain
  a temporary R13 accessor shim until the refreshed L0 base is available.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,293 passed; 185 failures exactly match the
  published P22 base-failure list; 5 deselected.
- **Metrics:** server/tools unchanged; product +1,775 and tests +807; budget ok.
- **Next:** nothing admitted; the orchestrator merges the refreshed R13 base and deletes the shim.

## 2026-10-06 — Correct L1 temporal and account controls

- **Why:** orchestrator acceptance review reproduced early-close, point-in-time,
  PDT matching, late-contingency, locate and atomic settlement defects in P22 L1.
- **What:** Make cutoffs close-relative, require complete minute sessions before
  terminal outcomes, use unadjusted as-of bars, same-session PDT matching and
  source-aware risk marks; fix late contingencies, locate evidence, directional
  liquidity, accrual spans, applied-quantity fees and per-fill transactions.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_fills.py
  tests/test_fills_v2.py tests/test_order_types.py tests/test_shorts.py
  tests/test_margin.py tests/test_accounts_settle.py tests/test_ledger.py
  tests/test_costs_ibkr.py tests/test_schema_v2.py`: 104 passed.
- **Metrics:** server/tools unchanged; budget check pending final full-suite gate.
- **Next:** run the R12 failure-set comparison, ruff and metrics, then report round 2.

## 2026-10-06 — Close P22 L1 review round 2

- **Why:** the orchestrator required the rejected L1 implementation to clear nine
  execution-correctness blockers and the listed accounting corrections.
- **What:** Add targeted regression probes for early close, bar completeness,
  as-of source isolation, late contingencies, directional liquidity, locate
  evidence, opening-date borrow, same-day PDT and atomic fee settlement.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,311 passed; the 185 failures exactly match
  the R12 base list; 5 deselected.
- **Metrics:** server/tools unchanged; product +362 and tests +381 from round 1; budget ok.
- **Next:** nothing admitted; await orchestrator acceptance and the R13 base refresh.

## 2026-10-06 — Add the versioned account intake contract

- **Why:** active P22 L2 sections 2.7 and 5 admit the v2 account boundary and fixes 4c–4e.
- **What:** Preserve v1 while adding v2 specs/intents, engine-stamped replayable receipts,
  monotonic order IDs, three-session carried marks, and NY-session account dates. R13 settings
  use `portfolio_accounts`; a small compatibility shim remains until revised L0 is merged.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_paper_accounts.py`
  passes all 26 cases.
- **Metrics:** server/tools unchanged; product/engine +450, tests +132; budget ok.
- **Next:** implement the transactional service and money-layer lifecycle.

## 2026-10-06 — Enforce the account money lifecycle

- **Why:** active P22 L2 sections 2.6 and 5 require independent account limits,
  structured loss/reconciliation halts, explicit resume, alerts, and retirement.
- **What:** Add transactional lifecycle services, total/per-account exposure checks,
  one-shot halt events and queued-order cancellation, concentration alerts, reconciliations,
  watch lists, replay verification, and MOC retirement orders using R13 settings.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_accounts_service.py
  tests/test_money.py` passes all 13 cases.
- **Metrics:** server/tools unchanged; product/engine +581, tests +222; budget ok.
- **Next:** expose deterministic results through the private loopback API and CLI.

## 2026-10-06 — Expose private account results and operations

- **Why:** active P22 L2 sections 2.7–2.8 require the account CLI, loopback API,
  private token boundary, read models, stable result hashes, and lazy L1 settlement wiring.
- **What:** Add all account reads and mutations, a mode-0600 bearer token command,
  deterministic account metrics, and an `engine.accounts` CLI. API receipt time is captured
  before its 180-second writer acquisition, and R13 side-table reads remain read-only.
- **Evidence:** focused account/server/no-bare-connect run passes all 121 cases; ruff is clean.
- **Metrics:** tools unchanged; product +720 (engine +369, server +351), tests +208; budget ok.
- **Next:** document the v2 contract and run the complete L2 acceptance matrix.

## 2026-10-06 — Publish the account v2 operating contract

- **Why:** active P22 L2 requires the public sections 2.6–2.8 contract without any
  private account identity, strategy parameters, or results.
- **What:** Document v2 specs/intents, R13 side-table settings, cutoff and replay rules,
  money halts, lifecycle commands, token-protected loopback routes, deferred intraday
  settlement, and deterministic private results. Add the three-tier MOO accounting proof.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_paper_accounts.py`
  passes all 27 cases.
- **Metrics:** server/tools/product unchanged; docs +92, tests +34; budget ok.
- **Next:** run focused acceptance, full-suite drift comparison, and final metrics.

## 2026-10-06 — Close P22 account-service acceptance

- **Why:** P22 L2 is done when its focused checks, full-suite drift comparison, ruff,
  and metrics budget pass without adding a failure outside the shared-base list.
- **What:** Confirm all account writers use the monotonic order sequence and R13 side-table
  settings. Focused acceptance and ruff are green; the complete run adds no failure beyond
  the 185 frozen-contract failures assigned to L3. P15 registration stayed deselected per R7.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,286 passed, 185 base-listed failures, 5 deselected.
- **Metrics:** server +351, tools unchanged, product +1,407; budget ok.
- **Next:** orchestrator merges revised L0, deletes the compatibility shim, and integrates L1/L2.

## 2026-10-06 — Correct the L0 foundation after review

- **Why:** R13 replaces portfolio columns with a side table and review reproduced replay, timing, lot and precision defects.
- **What:** Add the account-settings view/API, collision-safe sequence allocation across the four claimed writers, and time-ordered account replay.
  Complete day-trade lots, settlement transfers, early-close clocks, unrounded accruals, fractional fees and futures identity.
- **Evidence:** Snapshot base/lane rebuild comparison: 33 portfolios, 829 positions, cash_diff=0, position_diff=0; copies deleted.
- **Metrics:** server +5, tools unchanged, product +289 lines; budget clean.
- **Next:** L2 changes its remaining paper-account order allocator; L3 performs the R12 identity rebindings.

## 2026-10-06 — Preserve logical order identity during recovery

- **Why:** The orchestrator ruled that completed-tool recovery restores its retained logical id without calling the allocator.
- **What:** Restore a missing order from retained attribution/exit-rule identity and refuse an occupied conflicting id.
  Fold the still-required plan indexes and v5/cost-profile expectations into the lane; retire the obsolete consumer patch.
- **Evidence:** The 112-test L0, recovery, identity and documentation set passes; the conflict regression is included.
- **Metrics:** server +23, tools/product unchanged; budget clean.
- **Next:** Confirm the full-suite failure set is exactly the R12 baseline, then write final status.

## 2026-10-06 — Bound split adjustments by knowledge date

- **Why:** P22 L4 review reproduced future announced splits changing current bars
  and first-seen split rows retaining corrected or cancelled actions.
- **What:** Add an as-of adjusted-bar macro, current-date default view, corrected
  split upserts and complete-response withdrawals; overlap the cursor by 30 days.
  Run split capture before the options job through the same shared limiter.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_free_splits.py
  tests/test_free_sources.py tests/test_install_automation.py`: 83 passed.
- **Metrics:** server unchanged, tools +17, product/engine +83, tests +128; budget ok.
- **Next:** add the engine-owned first-fetch backfill and historical fallback.

## 2026-10-06 — Backfill first-seen price availability

- **Why:** P22 L4 review reproduced a pre-migration row losing its historic fetch
  time when the first post-migration refresh arrived before the planned backfill.
- **What:** Fall back through the stored `fetched_at` during conflict updates and
  expose `backfill_first_fetched_at`; L3's migration calls this helper once.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_db_bitemporal.py
  tests/test_collect.py tests/test_refetch_ticker.py tests/test_history_recovery.py`: 44 passed.
- **Metrics:** server/tools unchanged, product/engine +13, tests +52; budget ok.
- **Next:** make options prior-close reads immutable and share daily-bar budget fairly.

## 2026-10-06 — Share the bounded options budget fairly

- **Why:** P22 L4 review reproduced a global 400-contract limit starving later
  underlyings and an options reader mutating the grouped-daily store.
- **What:** Open prior closes read-only, require the adjusted view, divide the cap
  equally and rank 31-60 DTE near-money contracts. Verify receipt resume, missing
  cache/key and HTTP 429 refusals; cap account freshness at a logged 2,000 names.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_free_massive_options.py
  tests/test_collect_freshness.py tests/test_free_splits.py tests/test_free_sources.py
  tests/test_install_automation.py`: 96 passed.
- **Metrics:** server unchanged, tools +39, product/engine +9, tests +157; budget ok.
- **Next:** run the complete acceptance, refresh handoffs and publish round-two status.

## 2026-10-06 — Close L4 round-two review

- **Why:** Orchestrator review required as-of split handling, a migration helper,
  fair option capture, immutable inputs and bounded refusal/resume behavior.
- **What:** All eight blockers and minor cases are corrected; 140 focused tests,
  Ruff, systemd verification, both handoff patches and the metrics budget pass.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,320 passed, 104 integration-bound failures, 5 deselected.
- **Metrics:** server/tools/product unchanged since the implementation entries; budget ok.
- **Next:** L3 calls the backfill helper, routes the fail-soft nightly line, applies
  the positional-writer patch and rebinds the merged E1/sector/XS/P15 contracts.

## 2026-10-06 — Require strong evidence before split withdrawal

- **Why:** Round-three review reproduced an ambiguous empty 200 response withdrawing
  every active split in the capture window.
- **What:** Require explicit and complete pages, alarm on empty or excessive absence,
  and advance safe absences through `pending_withdrawal` on two complete refreshes.
  Old response replays cannot reactivate withdrawals; options read their explicit as-of view.
  Split refresh is fail-soft so aggregate options capture still runs.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_free_splits.py
  tests/test_free_massive_options.py tests/test_free_sources.py
  tests/test_install_automation.py`: 101 passed.
- **Metrics:** server unchanged, tools +4, product/engine +58, tests +183; budget ok.
- **Next:** run complete acceptance and publish round-three status.

## 2026-10-06 — Close L4 round-three review

- **Why:** Orchestrator re-review required strong withdrawal evidence, explicit
  option as-of prices, UTC defaults and fail-soft split scheduling.
- **What:** The withdrawal state machine and every incomplete/suspicious refusal
  pass 148 focused cases; Ruff, systemd, both handoff patches and budget pass.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,328 passed, 104 integration-bound failures, 5 deselected.
- **Metrics:** server/tools/product unchanged since the implementation entry; budget ok.
- **Next:** L3 applies the existing handoffs and rebinds merged runtime contracts.

## 2026-10-06 — Isolate and retry agent data capture failures

- **Why:** `pytest -q -W error -n 0 tests/test_agent_provider_responses.py::test_ticker_failure_preserves_other_verified_receipts` reproduced that an EFA response failure leaves only BIL committed and skips SPY.
- **What:** Add bounded transient retries to both external evidence sources and isolate per-symbol failures.
  Run all four capture stages through one aggregate runner so later stages still execute while the unit reports any failure.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_agent_provider_responses.py tests/test_agent_independent_price_evidence.py tests/test_agent_data_capture_runner.py` passed all 24 tests.
- **Metrics:** Server +235 lines and tests +181; tools and product unchanged. Budget passed.
- **Next:** Nothing admitted.

## 2026-10-06 — Preserve complete public league history

- **Why:** P22 L3 Phase A review reproduced inactive public equity disappearing from
  `league.csv` and required the final R13 API, strict hooks and fee-aware P15 sizing.
- **What:** Merge the refreshed L0/L4 base with both BUILDLOG histories; remove the R13
  shim; export all public equity while standings stay active-only; align the nightly
  validator and cache the API cohort. Missing hooks in present modules now raise, and
  P15 reserves its commission before sizing SPY. Shared-ledger league fills intentionally
  add 22 `sim_position_lots` rows on the snapshot (437 versus base's 415).
- **Evidence:** Two `python -m sim.league --date 2026-10-05 --rerun` snapshot-copy
  rehearsals produced byte-identical 50,044-byte CSV and 2,936-byte Markdown reports;
  the CSV retained all 73 rows for eight inactive portfolios. Both copies were deleted.
- **Metrics:** refreshed base plus review: server +280, tools +61, product +376; budget ok.
- **Next:** run the full Phase A suite, publish metrics and return revised status.

## 2026-10-06 — Validate legacy recovery bundles without R13 views

- **Why:** the post-review full suite reproduced 100 backup failures because recovery
  fixtures created before R13 correctly lack `portfolio_accounts_v`.
- **What:** The nightly validator uses the R13 public view on current stores and treats
  pre-R13 recovery schemas as all-public, preserving historical bundle verification.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --tb=no --deselect
  tests/test_p15_registration.py` — 4,323 passed; all 181 failures exactly match the
  refreshed 184-node Phase B list minus the three repaired driver tests.
- **Metrics:** server +6, tools/product unchanged; budget ok.
- **Next:** publish metrics and return revised Phase A status.

## 2026-10-06 — Publish reviewed P22 L3 Phase A metrics

- **Why:** the active P22 plan requires a fresh budget snapshot after the refreshed-base
  merge, byte-identity rehearsal and review corrections.
- **What:** Publish the reviewed Phase A repository metrics; no live state, producer,
  registered policy or service changed in this closure step.
- **Evidence:** `.venv/bin/python -m tools.metrics_snapshot --check-budget` — snapshot
  published with `budget.ok=true` and no violations.
- **Metrics:** server/tools/product unchanged; budget ok.
- **Next:** await the orchestrator's L1/L2 merge and Phase B signal.
## 2026-10-06 — Integrate R13 and close L1 round 3 findings

- **Why:** orchestrator re-review required the final L0/L4 base plus five bounded
  fixes for fail-soft locates, capture outages, PDT depletion, ordering and as-of locates.
- **What:** Merge the refreshed base with both BUILDLOG histories, remove temporary
  shims, reject unavailable locates per order, retain incomplete minute sessions,
  deplete recorded same-day lots, preserve receipt order and cutoff locate marks.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_fills_v2.py
  tests/test_shorts.py tests/test_margin.py tests/test_accounts_settle.py
  tests/test_order_types.py tests/test_schema_v2.py tests/test_ledger.py
  tests/test_costs_ibkr.py`: 98 passed.
- **Metrics:** pending final merged-base full-suite and budget gates.
- **Next:** run the merged full suite, ruff and metrics, then publish round-3 status.

## 2026-10-06 — Close P22 L1 review round 3

- **Why:** L1 must finish on the refreshed R13/L4 base with no regression beyond
  the integration-owned frozen-contract failures.
- **What:** The five re-review findings pass focused probes; the final L0 APIs are
  used directly, both merge histories are retained, and the lane is cleanly integrated.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,358 passed; 184 failures match the refreshed
  P22 base list; 5 deselected.
- **Metrics:** refreshed-base server/tools/product changes included; budget ok.
- **Next:** nothing admitted; await orchestrator acceptance.

## 2026-10-06 — Correct account service review findings

- **Why:** orchestrator review of d867b4a reproduced stale reconciliation re-halts,
  cancellation timing, contention mapping, result arithmetic and source-specific mark defects.
- **What:** Re-arm drawdown at resume while retaining the all-time peak, use only fresh/latest
  reconciliation evidence, cancel opening orders on retirement, serialize API writes, return
  retryable conflicts, hide private identities, and apply exact early-close/order windows.
  Allocation and alerts now honor each account's price source; result trade bp is fee-net.
- **Evidence:** focused L2/schema/server acceptance passes all 180 cases; ruff is clean.
- **Metrics:** tools unchanged; product/engine +121, server +23, tests +175; budget ok.
- **Next:** verify the L0 schema handoff and run the complete suite against the merged base.

## 2026-10-06 — Close P22 L2 review round two

- **Why:** orchestrator review required the final R13 base plus six account-service
  corrections and an L0-owned account-table initialization handoff.
- **What:** All review cases pass, the compatibility shim is gone, and the schema change is
  packaged in the L2 status patch directory. No claimed implementation remains uncommitted.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,342 passed, 184 base-listed failures, 5 deselected.
- **Metrics:** server/tools/product unchanged since the correction entry; budget ok.
- **Next:** orchestrator applies the L0 schema patch before integrating L1 and L2.

## 2026-10-06 — Tighten account resume and CLI refusal semantics

- **Why:** orchestrator re-review required halt-specific drawdown anchors, intake-aware
  activation on resume, and distinct CLI errors outside order submission.
- **What:** Drawdown resumes alone set a fresh anchor; reconciliation/daily/manual resumes
  retain the all-time threshold. Resume activates the legacy portfolio flag only after an
  accepted intake. Non-submit CLI failures now emit `error` instead of an order receipt.
- **Evidence:** focused L2/schema/server acceptance passes all 182 cases; ruff is clean.
- **Metrics:** server/tools unchanged; product/engine +8, tests +35; budget ok.
- **Next:** run the complete merged-base suite and publish final handoff status.

## 2026-10-06 — Close P22 L2 re-review

- **Why:** the accepted L2 re-review required three final resume and CLI semantics fixes.
- **What:** Regression coverage proves non-drawdown resumes retain the all-time threshold,
  inactive accounts stay inactive until an accepted intake, and only submit refusals use the
  order-receipt shape. The L0 account-table initialization patch remains ready for integration.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,344 passed, 184 base-listed failures, 5 deselected.
- **Metrics:** server/tools/product unchanged since the implementation entry; budget ok.
- **Next:** orchestrator re-merges L2 and applies its L0 schema handoff.

## 2026-10-06 — Rebind P22 runtime contracts explicitly

- **Why:** P22 R12 and the Phase B signal require the accepted L1/L2 runtime and
  commission break to replace every frozen dependency only through documented revisions.
- **What:** Wire borrow, interest, account settlement, halts and alerts into the league
  phases. Advance E1, sector and XS contracts with exact predecessor migrations; stamp
  walk-forward cohorts with revision 2. Every revision cites the owner's 2026-10-06
  decision, commissions and clock restart at parameterized D0, the schema/sequence/ledger
  refactor, and the byte-identical pre-D0 rehearsal. Strategies and verdict gates stay fixed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto` on the E1, sector,
  XS, walk-forward, hook, settlement and money suites — 273 passed; Ruff clean.
- **Metrics:** accepted L1/L2 plus revisions: server +405, tools +1, product +3,632; budget ok.
- **Next:** freeze this source commit, then bind P15 registration revision 13 to it.

## 2026-10-06 — Register P15 revision 13

- **Why:** P22 Phase B requires the final integrated source closure and D0 commission
  contract to be registered before any migration or deployment rehearsal.
- **What:** Bind 158 runtime files to the frozen source commit; register
  `ibkr_pro_tiered_v1`, the migration `--d0` break parameter and restarted book clocks.
  The explicit reason cites the owner's 2026-10-06 decision and byte-identical pre-D0
  replay. Scoring, labels, statistical gates and schedules remain unchanged.
- **Evidence:** `.venv/bin/python -m pytest -q -W error
  tests/test_p15_registration.py` — all 5 identity, constant, closure and source gates pass.
- **Metrics:** server/tools/product unchanged; tests/documentation only; budget ok.
- **Next:** run both-timezone full suites with registration enabled, then rehearse migration and accounts.

## 2026-10-06 — Rehearse D0 migration and private account lifecycle

- **Why:** P22 Phase B requires the real snapshot-copy migration, auction account,
  privacy and ledger verification path before revision 13 can close.
- **What:** Initialize legacy price schema before first-fetch backfill; admit a contingent
  MOC against its queued MOO; requeue v2 detail state on rerun; and let league call L1
  settlement inside its outer transaction. Future D0 disclosure stays absent pre-break.
- **Evidence:** Fresh snapshot: migration applied to 33 books and second run refused;
  2026-10-05 CSV/Markdown matched base byte-for-byte. A private $50k margin account filled
  MOO+MOC (fees $0.90), closed at equity $50,046.6388, stayed out of public reports, and
  `engine.accounts verify` returned `ok`; all database copies and temp credentials were deleted.
- **Metrics:** engine +20, server unchanged, tools +1, product +33; tests +119; budget ok.
- **Next:** freeze the corrected source, refresh revision 13 identities, then rerun both timezone suites.

## 2026-10-06 — Refresh revision 13 after rehearsal fixes

- **Why:** the accepted snapshot rehearsal found three integrated runtime defects whose
  corrections changed registered account, settlement and league source bytes.
- **What:** Keep every revision-13 policy field and reason unchanged; refresh only its
  frozen source commit, 158 exact file hashes and registration self-hash.
- **Evidence:** `.venv/bin/python -m pytest -q -W error
  tests/test_p15_registration.py` — all 5 source, closure and identity gates pass.
- **Metrics:** server/tools/product unchanged; budget ok.
- **Next:** rerun the complete UTC and Asia/Singapore suites on final bytes.

## 2026-10-06 — Close P22 L3 Phase B

- **Why:** Phase B completion requires final revision-13 bytes, both supported
  timezones green and the full migration/account rehearsal recorded.
- **What:** Freeze the rehearsal-corrected runtime and refreshed revision 13. The
  migration is one-shot, pre-D0 reports are byte-identical, private auction accounts
  settle with fees/equity/results and remain absent from public reports, and replay
  verification is clean. Temporary databases, token, specs and reports were deleted.
- **Evidence:** `TZ=UTC` and `TZ=Asia/Singapore .venv/bin/python -m pytest -q
  -W error -n auto` — 4,615 passed in each timezone, zero failures, registration enabled.
- **Metrics:** server/tools/product unchanged since the rehearsal fixes; budget ok.
- **Next:** nothing admitted.

## 2026-10-07 — Isolate account-phase failures from legacy books

- **Why:** final L3 review found an account exception could roll back every legacy
  portfolio's otherwise-valid nightly day.
- **What:** Commit the legacy day first, then run accrual, settlement, mark, halt and
  alert work in one transaction per account. A failed account rolls back locally,
  records structured `settlement_error` evidence and a WARN, while a separate final
  account status returns non-zero. Add `--no-accounts` and idempotent account retry on
  `--skip-if-done`. E1 migration now restamps both predecessor/current config hashes.
- **Evidence:** 179 focused league, account, replay, driver and E1 migration cases pass;
  planted one-account failure preserves legacy/peer commits and the escape hatch skips all phases.
- **Metrics:** server/tools unchanged, product +154; engine +5, tests +111; budget ok.
- **Next:** wait for the final L2 base, then merge and repin revision 13 last.

## 2026-10-07 — Publish the pre-repin checkpoint

- **Why:** the operating contract requires a budget snapshot before L3 pauses for the
  orchestrator's final base/re-pin signal.
- **What:** Publish the isolated-account implementation checkpoint; frozen hashes and
  revision 13 intentionally remain pending the final L2 merge.
- **Evidence:** `.venv/bin/python -m tools.metrics_snapshot --check-budget` — snapshot
  published with `budget.ok=true` and no violations.
- **Metrics:** server/tools/product unchanged; budget ok.
- **Next:** wait for final base, merge it, then repin revision 13 last.
## 2026-10-07 — Admit and expose contingent close orders

- **Why:** alpha integration reproduced a same-session MOC child being refused before its
  queued MOO parent could create holdings.
- **What:** Validate contingent buy/sell and short/cover pairs by accepted intent, account,
  instrument, session, queued state and parent quantity before holdings admission. Account order
  reads now expose child/parent intent IDs, and fill reads include the recorded reference price.
- **Evidence:** focused L2/schema/server acceptance passes all 187 cases; ruff is clean.
- **Metrics:** tools unchanged; product/engine +30, server +5, tests +123; budget ok.
- **Next:** run the complete merged-base suite and publish the alpha-integration handoff.

## 2026-10-07 — Close contingent-order integration fix

- **Why:** alpha integration required queued parent orders to authorize same-session contingent
  closes and required intent/fill reconciliation fields in the read API.
- **What:** Buy/MOC-sell and short/MOC-cover pairs now admit safely without current holdings;
  oversized, cross-account, mismatched-session/instrument and cancelled-parent children refuse.
  Order reads expose intent linkage and fills expose `reference_px`.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n auto --deselect
  tests/test_p15_registration.py`: 4,349 passed, 184 base-listed failures, 5 deselected.
- **Metrics:** server/tools/product unchanged since the implementation entry; budget ok.
- **Next:** orchestrator re-merges L2 into the integration branch.

## 2026-10-07 — Freeze the final L2-integrated runtime

- **Why:** the orchestrator's final base adds the accepted contingent-order/read-model
  contract and must precede the last revision-13 source pin.
- **What:** Merge the final L2 base, retain its stricter contingent contract and both
  regressions, and refresh the existing sector/XS successor digests for the isolated
  account-phase runtime. E1 and all verdict rules remain unchanged.
- **Evidence:** 167 focused sector, XS, E1, account intake/API and league isolation cases
  pass; runtime digests match and Ruff is clean.
- **Metrics:** server/tools/product unchanged apart from accepted base; budget ok.
- **Next:** freeze this source commit and repin revision 13 last.

## 2026-10-07 — Repin revision 13 to final sources

- **Why:** P22 requires registration identity to land after the final accepted L2 merge
  and isolated account-phase source commit.
- **What:** Keep revision-13 policies and reason unchanged; repin its 158-file closure,
  source commit and self-hash to the final runtime bytes.
- **Evidence:** `.venv/bin/python -m pytest -q -W error
  tests/test_p15_registration.py` — all 5 revision, closure, file and source gates pass.
- **Metrics:** server/tools/product unchanged; budget ok.
- **Next:** run both complete timezone suites, publish metrics and close L3.

## 2026-10-07 — Close isolated account settlement review

- **Why:** final acceptance requires the last L2 contract, isolated account failure
  handling, revision-13 repin and both timezone suites on identical final bytes.
- **What:** Preserve the stricter final contingent-order contract, freeze the isolated
  account-phase runtime, and repin revision 13 last to its 158-file final source closure.
- **Evidence:** `TZ=UTC` and `TZ=Asia/Singapore .venv/bin/python -m pytest -q
  -W error -n auto` — 4,623 passed in each timezone, zero failures, registration enabled.
- **Metrics:** server/tools/product unchanged since the final source and base merges; budget ok.
- **Next:** nothing admitted.

## 2026-10-08 — Reproduce account lifecycle review blockers

- **Why:** the approved P22 lifecycle review reproduced split and incorrectly ordered account
  processing across nightly, late settlement, replay, verification and retirement.
- **What:** Replace optional phase dispatch with one direct account processor. It orders fills
  by execution time, attaches isolated sources at production entry points, and atomically
  accrues, fills, marks, verifies, transitions risk, queues forced closes and finalizes retirement.
  Legacy reruns now rebuild only legacy books; signed corporate actions and completed-minute
  timestamps preserve short liabilities and prevent look-ahead.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_league_v2.py
  tests/test_accounts_service.py tests/test_accounts_settle.py` — 14 failures reproduce the
  reviewed defects before source changes.
- **Metrics:** tools unchanged; server +2; product +363 (engine +338, sim +25); tests +350.
- **Next:** add real nightly, late-CLI and account-API end-to-end lifecycle coverage.

## 2026-10-08 — Prove lifecycle behavior through production entry points

- **Why:** P22 acceptance requires the real account API, nightly driver and late-settle CLI,
  without mocked phase functions, plus exact lifecycle contract wording.
- **What:** Exercise read-only source attachment, long/short contingent auction pairs, delayed
  Massive settlement, retirement-to-flat, ledger-mismatch halting and account-safe legacy reruns
  through production entry points. Make verification itself atomic and document chronological
  fills, completed-minute timestamps, stale marks, forced closes and resume anchors.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error
  tests/test_account_sources.py tests/test_account_entrypoints_e2e.py
  tests/test_accounts_settle.py tests/test_accounts_service.py tests/test_accounts_api.py
  tests/test_fills_v2.py tests/test_margin.py tests/test_money.py tests/test_paper_accounts.py
  tests/test_settle.py tests/test_league_v2.py tests/test_shorts.py tests/test_ledger.py`
  — 187 passed.
- **Metrics:** server/tools unchanged; product +8; tests +322; docs +18.
- **Next:** refresh authorized frozen-runtime identities, then run both full timezone suites.

## 2026-10-08 — Refresh frozen forward runtime identities

- **Why:** P22 authorizes explicit rebinding of E1, sector and XS runtime contracts when account
  execution changes, while preserving their policies, baselines, evidence and verdict rules.
- **What:** Refresh only the three expected source digests for the reviewed lifecycle runtime.
  Contract versions, migration reasons, scoring, labels, gates, schedules and stored evidence are
  unchanged.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error
  tests/test_forward_review.py tests/test_xs_forward_review.py tests/test_experiment_runner.py
  tests/test_sector_forward_status.py tests/test_xs_forward_status.py
  tests/test_e1_forward_status.py` — 136 passed.
- **Metrics:** server/tools unchanged; product unchanged.
- **Next:** run the full suite, then repin P15 revision 13 without changing its contract values.

## 2026-10-08 — Repin P15 revision 13 after lifecycle correction

- **Why:** the lifecycle fix changes registered execution dependencies; the goal requires the
  source/closure gate green while leaving P15 at revision 13 for the orchestrator's later rebase.
- **What:** Add the now-required account service and source-attachment modules to the closure and
  refresh source file digests, source commit and registration self-hash only. Revision, scoring,
  labels, gates, schedules and book parameters are unchanged.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error
  tests/test_p15_registration.py -vv` — 5 passed.
- **Metrics:** server/tools/product unchanged.
- **Next:** run the full UTC and Asia/Singapore suites on the pinned bytes.

## 2026-10-08 — Close lifecycle boundary cases

- **Why:** final focused review required unambiguous ordering for uncertain limit contingencies,
  nonzero carry marks, and retiring-account exposure accounting.
- **What:** Refuse a market child whose limit parent may execute later, ignore invalid zero marks
  when choosing a carried liability, include retiring positions in aggregate exposure, and state
  signed corporate-action behavior in the settlement runbook.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error` over the 13 account,
  money, fill, league, replay and entry-point files — 188 passed.
- **Metrics:** server/tools unchanged; product +2; tests +17; docs +2.
- **Next:** refresh the frozen runtime/source digests on these final source bytes.

## 2026-10-08 — Bind final lifecycle boundary bytes

- **Why:** the accepted zero-mark and contingent-order boundary corrections are dependencies of
  the frozen sector and XS monitors.
- **What:** Refresh only those two source digests. E1 is unchanged; all strategy rules, controls,
  baselines, accumulated evidence and verdict thresholds remain unchanged.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error` over the six E1,
  sector and XS runtime/status test files — 136 passed.
- **Metrics:** server/tools/product unchanged.
- **Next:** repin P15 revision 13 to the final source commit, then run both full suites.

## 2026-10-08 — Repin revision 13 to final lifecycle sources

- **Why:** the final admitted carry-mark and contingent-order boundaries changed registered
  dependencies after the first lifecycle pin.
- **What:** Keep P15 at revision 13 and refresh only its source commit, affected file digests and
  self-hash. Add the two newly imported account modules to its exact dependency closure; no policy,
  scoring, label, gate, schedule or parameter changed.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error
  tests/test_p15_registration.py` — 5 passed.
- **Metrics:** server/tools/product unchanged.
- **Next:** publish the final metrics snapshot after the completed full suites and rehearsal.

## 2026-10-08 — Close P22 chronological account lifecycle

- **Why:** P22 acceptance requires every reviewed blocker fixed, both CI timezones green and a
  two-session rehearsal on a migrated snapshot copy.
- **What:** The final revision-13 closure passed both full suites. A copied 7.9 GB snapshot
  migrated 33 portfolios with `--d0 2026-10-19`; a generic $50k account then completed ten
  MOO/MOC pairs on each of 2026-10-06 and 2026-10-07. Cash equalled equity with no positions,
  zero reconciliation difference and `verify=ok` after each session; late settle was a no-op.
  The scratch database was deleted.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -o addopts='' -q -W error -n auto &&
  TZ=Asia/Singapore .venv/bin/python -m pytest -o addopts='' -q -W error -n auto`
  — 4,644 passed in each timezone, including all five P15 registration tests.
- **Metrics:** server +2, tools unchanged, product +475; tests +759; budget ok.
- **Next:** nothing admitted.


## 2026-10-08 — P22 isolated account valuation and execution

- **Why:** active P22 plan and the orchestrator's reproduced lifecycle findings.
- **What:** record the binding isolation, valuation, transaction and recovery rules;
  share carried valuation, keep financing through retirement, cap contingent closes,
  and reconcile cash within half a cent with financing before fills.
- **Evidence:** `pytest -q tests/test_p22_round2.py` — 8 passed; 7 failed on baseline.
- **Metrics:** server -5 LOC, tools +0 LOC, product -138 LOC.
- **Next:** isolate source contention and account corporate actions.

## 2026-10-08 — Isolate source contention and account dividend booking

- **Why:** P22 round-2 writer-lock, legacy-dividend and CLI error reproductions.
- **What:** copy source rows through short-lived read-only attachments with retries;
  defer dependent accounts, keep halt/cancel independent, and book account dividends
  inside their transaction. Captured splits change signed lots, orders and replay
  independently of legacy price restatement. Late CLI propagates account errors.
- **Evidence:** `pytest -q tests/test_p22_round2.py tests/test_actions.py` — 34 passed;
  writer/dividend regressions failed before their fixes; split regression failed too.
- **Metrics:** server -5 LOC, tools +0 LOC, product +18 LOC since baseline.
- **Next:** captured splits and chronological late recovery.


## 2026-10-08 — Recover old account sessions and preserve v1 routing

- **Why:** P22 round-2 late-mark, stranded-order and migration reproductions.
- **What:** replay unresolved sessions oldest-first through dependent later marks,
  merge stored and new fills chronologically, append financing corrections, and
  preserve v1 league routing; migration reports and refuses unacknowledged route changes.
- **Evidence:** store-copy rehearsal: 42 fills, 2 late fills, flat positions,
  cash/equity $49,991.872499436395, financing booked, reconciliation ok; copy deleted.
  Both frozen-environment timezone suites: 4,582 passed / 81 failed, all frozen
  P15/sector/XS identity gates; 50 focused tests passed. Locked-version rehearsal matched.
- **Metrics:** server +0 LOC, tools +28 LOC, product +218 LOC.
- **Next:** orchestrator re-pins P15 and frozen runtime identities, then acceptance.

## 2026-10-08 — Issue P15 registration revision 13

- **Why:** The read-only production snapshot rejected a valid 2-to-3-share SPY cash reinvestment, and mature event labels were not refreshed before overnight reporting.
- **What:** Validate only documented cash-resized SPY reinvestments against both fill ledgers; keep every other mismatch fatal.
  Run the existing idempotent event-label maturation after nightly prices and before reporting; bind the exact sources as revision 13.
- **Evidence:** `TZ=<UTC|Asia/Singapore> .venv/bin/python -m pytest -q -W error -n auto` reached 100% in both timezones (4,411 collected), exit 0; the snapshot validator reports `P15 evidence validation: ok`.
- **Metrics:** server +92, tools unchanged, product +20; budget ok.
- **Next:** Nothing further admitted; the orchestrator may deploy revision 13 from the pushed branch.

## 2026-10-08 — Refresh integrated forward identities

- **Why:** P22 integration requires the frozen sector, XS and E1 identities to bind the
  merged lifecycle bytes without changing any registered rule or value.
- **What:** Refresh the sector and XS runtime digests. E1 recomputed byte-identically, so
  its existing digest remains unchanged; all three contract versions and rules stay fixed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_forward_review.py
  tests/test_xs_forward_review.py tests/test_experiment_runner.py` — exit 0; 94 collected.
- **Metrics:** server/tools/product LOC unchanged.
- **Next:** issue P15 registration revision 14 on the frozen integrated source commit.

## 2026-10-08 — Register integrated P15 revision 14

- **Why:** P22 integration requires a new registered identity on top of main's revision-13
  validator and label-timing correction before the 2026-10-18 deployment window.
- **What:** Bind the 161-file merged dependency closure as revision 14, including the account
  action and shared valuation modules. Register P22 commissions from migration `--d0`, restarted
  book clocks and the account engine; scoring, labels, gates and schedules stay unchanged.
- **Evidence:** `.venv/bin/python -m pytest -o addopts='' -q -W error -rN
  tests/test_p15_registration.py` — 5 passed, exit 0.
- **Metrics:** server/tools/product LOC unchanged.
- **Next:** run every CI static gate and the full suite in both supported timezones.

## 2026-10-08 — Close P22 revision-14 integration

- **Why:** P22 integration acceptance requires main's revision-13 hotfix, the account runtime,
  revision 14 and both supported-timezone suites to pass on identical committed bytes.
- **What:** Preserve the validator and label-maturation hotfix, bind P22 through revision 14,
  and refresh the frozen sector and XS identities. All blocking Ruff, compile and shell gates pass;
  the workflow's advisory C90 check retains its two existing findings.
- **Evidence:** `TZ=UTC ... pytest -o addopts='' -q -W error -n auto -rN &&
  TZ=Asia/Singapore ... pytest -o addopts='' -q -W error -n auto -rN` — 4,667 passed
  in each timezone, exit 0 in both.
- **Metrics:** server +89, tools +28, product +731; budget ok.
- **Next:** open the draft PR and require hosted CI before the 2026-10-18 deployment window.



## 2026-10-08 — Reproduce P22 round-3 accounting failures

- **Why:** active P22 and the round-3 orchestrator rulings admit the accounting and deployment corrections.
- **What:** added API/nightly/late-CLI regressions for delisting recovery, verification failure,
  borrow timing, debit intervals, split trade results, split receipts, carried marks and migration.
  Recorded the binding round-3 rulings in the feedback ledger.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p22_round3.py` — nine failures before fixes;
  cash delisting recovery restored shares and lost $10,000; flat days tripled interest.
- **Metrics:** production LOC unchanged.
- **Next:** replace parallel accounting reconstruction with the shared chronological ledger path.

## 2026-10-08 — Share chronological account replay and lot performance

- **Why:** active P22 round 3; the committed regressions reproduced delisting reversal,
  future-close borrow financing, flat-day interest and split-corrupted trade results.
- **What:** one ledger event sequence now merges actions, financing and timestamped executions.
  Late recovery uses every event type and rolls back failed verification; results replay the same
  matched-lot accounting on an isolated in-memory copy. Borrow uses the opening observation
  boundary; zero-interest events advance the debit checkpoint. Removed both parallel reconstructions.
- **Evidence:** `.venv/bin/python -m pytest -q -n 4 tests/test_p22_round2.py tests/test_p22_round3.py tests/test_shorts.py tests/test_paper_accounts.py tests/test_migrate_cost_profiles.py` — 76 passed.
- **Metrics:** production LOC reduced; final snapshot follows verification.
- **Next:** finish admission and migration corrections, then rehearse deployment and rollback.

## 2026-10-08 — Preserve account receipts and carried admission marks

- **Why:** P22 round-3 API regressions reproduced split retry conflicts and stale-held-name refusals.
- **What:** intake checks its immutable evidence and recorded split adjustments before returning
  the original receipt. Admission now shares source-aware marks with settlement and API reads;
  existing carried marks remain valued and the position response exposes their stale flag.
- **Evidence:** `.venv/bin/python -m pytest -q -n 4 tests/test_paper_accounts.py tests/test_p22_round2.py tests/test_p22_round3.py tests/test_shorts.py tests/test_migrate_cost_profiles.py` — 76 passed.
- **Metrics:** removed the separate admission valuation functions.
- **Next:** preserve all existing routes in the commission migration.

## 2026-10-08 — Migrate commissions without rerouting existing books

- **Why:** P22 round 3 requires zero migration route changes and deployed registration revision 14.
- **What:** migration changes only the cost profile, retains all existing account settings,
  and reads the P15 registration revision from its JSON. Removed route inference and its flag.
  The retained P15 legacy fill path charges the commission and debits the same book's cash.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_p22_round3.py -k 'migration_revision or p15_pending'` — 2 passed; base revision reproduction wrote 13 instead of 14.
- **Metrics:** migration implementation reduced by 48 lines.
- **Next:** rehearse deploy and rollback on the disposable snapshot copy.

## 2026-10-08 — Bind undeployed P22 runtime corrections

- **Why:** the round-3 accounting changes touch registered source files before revision 14 deploys.
- **What:** refreshed the sector and XS runtime identities for the corrected shared ledger,
  documenting the undeployed amendment. Strategy rules and prospective records remain frozen.
- **Evidence:** P15 and full-suite identity gates run with the final revision 14 re-pin.
- **Metrics:** two runtime amendment lines added.
- **Next:** pin revision 14 to this corrected source commit and run both timezone suites.

## 2026-10-08 — Complete account projection integration checks

- **Why:** round-3 full suites found the account scratch connection outside the required DB factory.
- **What:** routed the in-memory results replay through the shared connection factory and refreshed
  undeployed runtime bindings. Restored the BUILDLOG tail marker required by the structural check.
- **Evidence:** full suites identified this factory violation; focused and both-timezone reruns follow.
- **Metrics:** production LOC unchanged.
- **Next:** finalize revision 14 identities, then complete the deployment rehearsal.

## 2026-10-08 — Re-pin undeployed P15 revision 14 after round 3

- **Why:** the orchestrator requires revision 14 to bind the round-3 corrections before deployment.
- **What:** refreshed registered file identities, source commit and canonical registration hash,
  retaining revision 14 and the frozen strategy, scoring and statistical rules. Updated the account contract.
- **Evidence:** full suites under `TZ=UTC` and `TZ=Asia/Singapore` both exited 0 with
  `.venv/bin/python -m pytest -q -W error -n auto`; Ruff, audits, build and UI checks passed.
- **Metrics:** server 0, tools −48, product −55 LOC; hygiene budget passes.
- **Next:** finish and record the disposable deployment/rollback rehearsal, then check PR CI.

## 2026-10-08 — Rehearse P22 deployment and complete rollback

- **Why:** round 3 requires executable commands and a complete disposable-store rehearsal.
- **What:** corrected backup syntax, canonical paths, readiness checks, unchanged-route migration,
  unit installation and explicit writer quiescence in both deployment documents. Recorded the transcript.
  Migration kept 33 routes and wrote revision 14; two captured sessions filled four orders with $1.44 fees.
- **Evidence:** the complete rehearsal exited 0; both sessions verified, every isolated writer stopped,
  and the restored database matched the backup before and after the pre-deploy API health check.
- **Metrics:** server 0, tools −48, product −55 LOC from the starting snapshot; budget passes.
- **Next:** check the final PR commit's CI and report completion.


## 2026-10-08 — Reproduce P22 round-4 ledger consumers

- **Why:** P22 round-4 review and the active P22 plan admit all requested accounting corrections.
- **What:** Added regressions for fee-aware P15 validation, historical dividends, resume
  recovery, persisted lots/equity, FIFO PDT preview, optional whole shares and bash syntax.
- **Evidence:** `pytest tests/test_p22_round4.py -q -W error` reproduces P15 runtime rejection,
  re-halt after resume, undetected lot/equity corruption, PDT and specification refusals.
- **Metrics:** unchanged production code.
- **Next:** consolidate the failing consumers into the chronological ledger.

## 2026-10-08 — Accept documented account sizing and executable runbook examples

- **Why:** P22 round-4 regressions rejected optional whole_shares and bash block 2.
- **What:** Admitted the documented boolean and quoted shell placeholders.
- **Evidence:** `pytest tests/test_p22_round4.py -k 'creation or bash' -q -W error` passes.
- **Metrics:** unchanged production LOC outside tests.
- **Next:** finish shared accounting consumers and revision 14 binding.

## 2026-10-08 — Consolidate P22 accounting and risk consumers

- **Why:** round-4 fail-first tests reproduced all four blockers; the sweep found two more
  replay loops in P15 recovery and paper attribution.
- **What:** Shared ledger prefixes now drive cash, historical dividend entitlement and
  verification of lots and source-marked equity. P15 shares executor sizing, PDT previews
  share FIFO matching, and late recovery retains recorded resume anchors and halt history.
  Removed the competing P15 and attribution reconstructions; kept their evidence gates.
- **Evidence:** `pytest tests/test_p22_round4.py -q -W error` → 23 passed; the affected
  accounting, legacy-book, attribution and round-2/3 regressions pass.
- **Metrics:** snapshot pending closure; production code reduced by removing replay loops.
- **Next:** bind revision 14 and rehearse legacy D0 and revision-13 rollback boundaries.

## 2026-10-08 — Bind undeployed runtime accounting consolidation

- **Why:** P22 round 4 changes registered generic accounting dependencies.
- **What:** Rebound the still-undeployed sector and XS runtime identities to the shared
  ledger consumers. Strategy rules, evaluation criteria and historical records are unchanged.
- **Evidence:** `ruff check .` passes; revision-14 registration and suite follow this source commit.
- **Metrics:** unchanged production LOC.
- **Next:** re-pin revision 14, then execute acceptance checks and rehearsal.

## 2026-10-09 — Reuse one ledger pass for dividend entitlement dates

- **Why:** the round-4 snapshot rehearsal exercised many simultaneous late dividends.
- **What:** Project all eligible entitlement closes in one chronological replay per book;
  exclude tickers never acquired by fills or stock consideration.
- **Evidence:** `pytest tests/test_p22_round4.py tests/test_portfolio.py tests/test_regressions.py -q -W error` passes.
- **Metrics:** recorded in the closure snapshot.
- **Next:** finish the disposable captured-session rehearsal and CI.

## 2026-10-09 — Re-pin undeployed P15 revision 14 for round 4

- **Why:** round-4 source changes require explicit registration before deployment.
- **What:** Re-pinned revision 14 and its exact self-identity; frozen scoring, labels,
  statistical gates and schedules are unchanged. Legacy settlement tables remain optional.
- **Evidence:** `pytest tests/test_p15_registration.py -q -W error` → 5 passed;
  the 69 dividend, portfolio and round-4 regression cases pass.
- **Metrics:** refreshed in the closure snapshot.
- **Next:** complete captured-store rehearsal, full-suite and PR CI acceptance.

## 2026-10-09 — Verify round-4 source and publish the metrics snapshot

- **Why:** P22 round 4 requires the full suite, revision 14 and captured-session evidence.
- **What:** Published the completed source checks and accounting LOC reduction. The
  disposable rehearsal has preserved all 33 routes and passed P15 validation on two
  captured post-D0 sessions; final rollback and PR CI evidence is retained in the handoff.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error -n auto` → 4,701 passed;
  Ruff and all five P15 registration tests pass.
- **Metrics:** server -67, tools 0, product -37, tests +153 versus October 8.
- **Next:** finish rehearsal cleanup and record the final PR CI verdict in STATUS.

## 2026-10-09 — Preserve the equity check before late recovery

- **Why:** `pytest tests/test_p22_round4.py -k late_recovery_does_not_hide -q -W error`
  showed recovery overwriting a checkpoint changed by $100 without persisting a mismatch.
- **What:** Validate the original checkpoint using its recorded carried marks, then
  validate refreshed source marks after recovery; never skip the equity comparison.
- **Evidence:** the 87 account, round-2/3/4 and entrypoint regression cases pass;
  revision-14 registration and Ruff pass.
- **Metrics:** refreshed after the correction.
- **Next:** re-pin revision 14 and finish final CI acceptance.

## 2026-10-09 — Reproduce P22 historical event failures

- **Why:** active P22 and the round-5 orchestrator ruling require one verified replay path.
- **What:** Added real nightly, settlement and verify CLI regressions for historical resume,
  split-after-sale, corrupted retry checkpoints, discounted delisting, FIFO and debit interest.
- **Evidence:** `pytest tests/test_p22_round5.py -q -W error` → 10 failed on the old behavior.
- **Metrics:** production LOC unchanged.
- **Next:** implement checkpoint prefix verification and atomic chronological replay.

## 2026-10-09 — Replay historical account events from verified checkpoints

- **Why:** P22 round 5 reproduced four chronological accounting blockers and the related FIFO/interest defects.
- **What:** Bound checkpoint state and marks to their ledger prefixes, verified before mutation,
  and unified historical settlement and risk entry points around atomic rewind/replay.
  Retained mismatch evidence outside rollback; removed inferred day trades and charged
  elapsed debit interest before opening cash movements. Rebound the undeployed runtime.
- **Evidence:** `pytest tests/test_p22_round5.py tests/test_settle.py tests/test_accounts_service.py
  -k 'not randomized' -q -W error -n 6` → 47 passed.
- **Metrics:** closure snapshot follows complete validation.
- **Next:** finish randomized delivery checks and revision-14 binding.

## 2026-10-09 — Bind round-5 replay and delivery regressions to revision 14

- **Why:** round 5 requires randomized real-entrypoint equivalence, rehearsal references and registration.
- **What:** Added 12 seeded paired chronological/delayed runs over seven sessions, plus
  rollback evidence and split-before-delisting regressions. Cited both round-4 rehearsals.
  Re-pinned undeployed revision 14, including the newly reached late-recovery dependency.
- **Evidence:** `pytest tests/test_p22_round5.py -k randomized -q -W error -n 6` → 12 passed;
  all five P15 registration checks pass.
- **Metrics:** server/tools unchanged; product +254 versus the initial snapshot.
- **Next:** full suite, both CI time zones, and PR #13 status.

## 2026-10-09 — Back synthetic risk checkpoints with ledger events

- **Why:** full validation exposed old fixtures that replaced unbacked cash/equity state.
- **What:** Gave synthetic loss marks real adjustment events and moved the same-session
  resume after its close. Backed the liquidity short with its immutable fill and made
  retained retry checkpoints match their independently funded account balances.
- **Evidence:** `pytest tests/test_accounts_settle.py tests/test_money.py -q -W error -n 6` → 40 passed.
- **Metrics:** production LOC unchanged.
- **Next:** finish full-suite and both-timezone CI acceptance.

## 2026-10-09 — Publish round-5 validation corrections and metrics

- **Why:** P22 round 5 requires all acceptance checks and a published metrics snapshot.
- **What:** Indexed the retained rehearsal evidence and published the final accounting
  metrics. The initial full run passed 4,720 cases; its six fixture/index failures
  are corrected without changing production verification.
- **Evidence:** `pytest tests/test_documentation_integrity.py tests/test_operating_contract.py
  tests/test_p15_registration.py tests/test_accounts_settle.py tests/test_money.py
  -q -W error -n 6` → 62 passed; Ruff and the metrics budget pass.
- **Metrics:** server 0, tools 0, product +254 versus the initial October 9 snapshot.
- **Next:** confirm both-timezone CI on PR #13 and record the writer verdict in STATUS.

## 2026-10-09 — Publish the generated metrics index

- **Why:** the required metrics publication updates its index alongside the JSON snapshot.
- **What:** Included the generated October 9 index row and its source/test LOC deltas.
- **Evidence:** `python -m tools.metrics_snapshot --check-budget` → budget ok.
- **Metrics:** unchanged from the published snapshot.
- **Next:** finish PR #13 CI acceptance and write STATUS.

## 2026-10-10 — Reproduce round-6 accounting and risk blockers

- **Why:** P22 round 6 replaces case-specific recovery with the complete accounting fold.
- **What:** Added fail-first regressions for pending orders across splits, cash identities
  across dates, past resume requests and arbitrary replay exceptions at three entry points.
  Recorded the superseding accounting/risk rulings and reproduced the list CLI crash.
- **Evidence:** `pytest -q -W error tests/test_p22_round6.py` → seven failures before fixes.
- **Metrics:** production LOC unchanged.
- **Next:** remove checkpoint restoration and historical-risk replay.

## 2026-10-10 — Fold complete account history and process risk as-known

- **Why:** P22 round 6 rulings A–D and the four fail-first lifecycle blockers.
- **What:** Replaced checkpoint recovery with inception folds and immutable receipt units.
  Removed historical-risk replay; corrected curves drive current drawdown and daily loss.
  All fold/settlement/verification failures roll back, then durably record a mismatch and halt.
  Results verify through the account writer; list accepts its list payload.
- **Evidence:** `pytest -q -W error -n 8 tests/test_p22_round{2,3,4,5}.py
  tests/test_accounts_settle.py tests/test_money.py tests/test_account_results.py` → 110 passed.
- **Metrics:** pending final snapshot; accounting paths have a net reduction.
- **Next:** complete generated-delivery seeds and revision-14 acceptance.

## 2026-10-10 — Exercise delayed delivery and require the approved deploy identity

- **Why:** P22 round 6 requires generated lifecycle coverage and explicit migration gates.
- **What:** Replaced the narrow generator with forward/reverse splits, pending and filled
  orders, late bars, dividends, cash delistings, weekend debit interest and partial recovery.
  Added an independent as-known risk oracle, post-resume losses and replay failures.
  The runbook records the approved SHA and checks it, revision 14 and registration before migration.
- **Evidence:** `pytest -q -W error tests/test_p22_round6.py -k generated -n 8` → 8 passed.
- **Metrics:** server +5, tools 0, product -367 versus the initial snapshot.
- **Next:** complete 200 seeds, revision 14 registration, full suite and PR #13 CI.

## 2026-10-10 — Bind round-6 source to undeployed revision 14

- **Why:** P22 round 6 requires re-pinning changed registered files without revision 15.
- **What:** Bound the complete-fold source commit and its exact registered file hashes.
  Kept revision 14 and its frozen scoring, labels, gates and schedules.
- **Evidence:** `pytest -q -W error tests/test_p15_registration.py
  tests/test_documentation_integrity.py tests/test_operating_contract.py -n 4` → 22 passed.
- **Metrics:** server +5, tools 0, product -367 versus the initial snapshot.
- **Next:** finish 200 seeds, full-suite and both-timezone PR #13 CI.

## 2026-10-10 — Close full-suite bindings and generated-delivery acceptance

- **Why:** P22 round 6 full validation found stale undeployed runtime hashes and one caller-contract regression.
- **What:** Preserved the nightly transaction argument and refreshed the undeployed sector/XS
  source bindings for complete accounting folds. Their versions, rules and evidence stay frozen.
  Fixed CI to four representative seeds; the 200-seed local run covers the larger generator.
- **Evidence:** `P22_PROPERTY_SEEDS=200 pytest -q -W error tests/test_p22_round6.py
  -k generated -n 16` → 200 passed; the 14-case CI subset took 88.56 seconds with two workers.
- **Metrics:** server +5, tools 0, product -364 versus the initial snapshot.
- **Next:** bind the final source commit to revision 14 and require both PR #13 CI time zones green.

<!-- append-only-tail: insert new verified entries immediately above this line -->
