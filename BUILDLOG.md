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

<!-- append-only-tail: insert new verified entries immediately above this line -->
