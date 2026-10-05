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

<!-- append-only-tail: insert new verified entries immediately above this line -->

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
