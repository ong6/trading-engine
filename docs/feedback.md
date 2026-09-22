# Owner feedback ledger

Dated verdicts from the owner about the repo or agent behaviour, each with the rule it
changed. The newest entry overrides any older document, including `AGENTS.md`. Agents read
this second, and append here (never rewrite) when the owner gives a verdict in conversation.

Format: date, the verdict in the owner's terms, the rule change, where it was applied.

## 2026-09-18 — Review of progress; move to maintain mode

**Verdict.** Rated 6/10 overall: engineering rigor 8, research honesty 9, research output 3,
scope control 3, process health 4. The loop had drifted from "find an edge" to "build
governance for an edge that doesn't exist." `server/` at 46k lines is larger than the whole
product and almost all of it serves a broker that has no authority. Yesterday's single commit
added 161 files and 61k lines against a standing order for small reviewable commits. BUILDLOG
entries average 741 lines and repeat four hashes each. Owner asked for the docs, skills,
metrics and feedback layers to be hardened so long-running LLM sessions stop doing work "we
don't need yet", then for follow-up plans.

**Rule changes.**

1. Mode is MAINTAIN. Default session outcome is verify, report, stop. → `AGENTS.md`.
2. Every change must pass the admission test (backlog row, approved plan, or reproduced
   defect). → `AGENTS.md`.
3. `server/`, `tools/`, and the research runtime are frozen at ceilings in
   `docs/scope-budget.json`; the test suite fails on growth. → `tests/test_operating_contract.py`.
4. BUILDLOG entries: at most 25 lines, one hash. → `AGENTS.md`, budget, test.
5. No new documentation-pinning tests. → `AGENTS.md`, `docs/scope.md`.
6. `docs/live-readiness-goal.md` is reference, not the work queue; workstreams C, D, E are
   frozen pending the P4 decision. → banner in that file, `docs/scope.md`.
7. A drift metrics snapshot closes every session. → `tools/metrics_snapshot.py`,
   `docs/metrics.md`.
8. Owner verdicts are written here and applied in the same session. → `AGENTS.md`.

**Plans opened.** P1 appliance mode, P2 league collapse, P3 point-in-time data, P4 broker
decision. All `proposed`; owner promotes.

**Ceiling changes.** None yet. Record any raise here with the reason before editing the
budget file.

## 2026-09-18 — Repo made public; history scrubbed, dates untouched

**Verdict.** Owner asked to publish the repo as a showcase for quant and trading-firm readers and
to link it from junxiong.dev. Owner also suggested spreading commit dates across a year; declined,
because the artifacts are all dated from 2026-07-15 and a false timeline would be both dishonest
and trivially detectable. The real record (first commit 2026-07-16, nightly since 2026-07-17)
stands.

**What changed.** History rewritten with `git filter-repo` to replace an employer email, a devbox
home path, an internal tool name and an agent co-author trailer; every commit date and count is
unchanged (201 commits). A separate working-tree scrub commit became empty under the rewrite and was pruned by filter-repo.
Visibility set to public. Any existing clone must be re-cloned.

**Rule changes.**

1. Public repo: no employer, devbox or internal-tool identifiers in any file or commit message.
   "One Linux box" is the only description of the host. → `AGENTS.md` absolute rules.
2. Commit dates are never edited. → this ledger.

## 2026-09-18 — Resume bounded agent decisions and alpha research

**Verdict.** The owner explicitly asked to resume feature implementation so a constrained agent
can control decisions and the deterministic algorithm engine can search for alpha. This overrides
the default MAINTAIN-only verdict for the two bounded plans below. It does not authorize broker
connectivity, credentials, live orders, real capital, weakening frozen evidence, or tuning an
existing strategy after observing its results.

**Rule changes.**

1. P5 is approved and active: implement one separately attributed, simulator-only agent paper
   decision path that fails to no action and has no broker submission surface.
2. P6 is approved: add one theory-led, pre-registered deterministic alpha experiment with a
   frozen control, costs, sample rule, and kill criterion. Existing forward records stay frozen.
3. BUILD mode is permitted only inside P5 and P6 budgets; all unrelated frozen layers remain
   frozen.
4. P4 intent is **yes for continued capital-disabled execution research**. Real-broker operation
   remains undecided and technically absent; any future broker connection requires a new explicit
   owner decision and plan.

**Ceiling changes.** P5 may add 900 lines under `server/` and 200 under `tools/`; P6 may add
900 lines under `farm/`. The corresponding ceilings are raised before implementation.

## 2026-09-18 — Independent review is a completion gate

**Verdict.** The owner required fresh checking agents after implementation and directed continued
remediation until those agents were satisfied. That instruction expands P5/P6's original commit
budgets only for review findings; it does not expand feature scope or LOC ceilings. Each source
commit remains below the repository's 1,500-line ceiling. P5 and P6 close only after the repeated
safety, methodology, and regression reviews, the full suite, and publication of final evidence.

## 2026-09-19 — Approve the P1-P4 roadmap and remote publication

**Verdict.** The owner approved the four proposed follow-up plans and explicitly authorized
completed commits to be pushed. Work proceeds in the documented order, beginning with P1.

**Rule changes.**

1. P1 is active; P2 is approved with its listed eleven-book retirement set confirmed.
2. P3 is approved for its no-purchase vendor comparison. Purchase and ingestion still require
   the owner to select a vendor and spending ceiling.
3. P4 is approved as a decision plan. Execution or archival still requires the owner to choose
   its explicit yes/no branch; broker connections, credentials, and real capital remain forbidden.
4. The agent may push completed, verified commits to the configured `origin/main` upstream.

## 2026-09-20 — Separate the research-data and execution vendors

**Verdict.** The owner delegated the long-term provider choice, naming Moomoo and IBKR as likely
candidates. The selected architecture is IBKR for eventual broker execution and Sharadar via
Nasdaq Data Link for point-in-time US-equity research data. Norgate is the research-data fallback;
Moomoo remains a secondary broker candidate.

**Rule changes.**

1. P4 takes the **yes, real-broker operation eventually** branch, with IBKR as the primary target.
2. A separate execution-layer plan is required before implementation. No broker connection,
   credentials, market-data subscription, live order, or capital is authorized by this decision.
3. P3 recommends Sharadar for purchase review because broker APIs do not establish complete
   delisted-security, historical-membership, and publication-timestamped fundamental coverage.
4. P3 remains purchase-blocked until the owner sets a spend ceiling and accepts current licence
   terms; no vendor account or data ingestion is authorized yet.

## 2026-09-20 — Approve an autonomous S$10,000 paper comparison

**Verdict.** The owner set S$10,000 as the starting capital envelope, required fully AI decisions
without routine per-order approval, requested several months of paper operation first, and asked
for algorithm-only, AI-only, and algorithm-plus-AI designs with sound logging and observability.

**Rule changes.**

1. P7 is approved and active for a simulator-only three-arm comparison. “Fully AI” delegates the
   paper policy choice, not data admission, sizing, risk, accounting, execution, or kill switches.
2. Each counterfactual arm models the same frozen USD equivalent of S$10,000; this is one owner
   capital envelope, not three deployable allocations. The conversion must be independently
   recorded when the trial activates.
3. The first review gate is 90 calendar days and 60 completed sessions; no comparative strategy
   verdict is allowed before 12 paired monthly decisions. No tuning occurs mid-cohort.
4. P7 permits only internal simulator orders. Broker connections, credentials, subscriptions,
   live orders, and real capital remain forbidden and need later explicit plans.
5. The S$10,000 envelope is not a P3 vendor-data budget. Sharadar/Norgate purchase remains blocked
   on a separate initial and recurring spend decision.

**Ceiling changes for later P7 implementation.** `server/` 48,100 lines, `tools/` 7,400 lines,
and `sim/` 7,000 lines. These are caps, not targets; P7 requires reuse of the existing evidence,
attribution, simulator, scheduler, and fault-drill machinery.

## 2026-09-20 — Use Trae under an observable paper-only identity

**Verdict.** The owner directed the project to fix and exercise the working Trae model rather than
leave the paper programme blocked on an unavailable provider field. A real tool-free inference
succeeded, while raw upstream metadata exposed a model family and request ID but no immutable
provider build.

**Rule changes.** P7 paper operation may use Trae when every response is bound to the exact proxy
source, CLI runtime, catalog/routing identity, prompt/toolset, upstream-reported model family, and
request identity. Any visible drift fails closed. This acceptance is simulator-only; a provider-
issued immutable revision remains required before any later real-capital authorization.

## 2026-09-22 — Approve a daily opportunity agent

**Verdict.** The owner asked the agents to run daily, identify market-moving context and standout
stocks, assess whether each should be ignored, watched, held, or swing-traded, retain multi-day
price alerts, and implement the necessary flow now. The daily programme supplements rather than
changes the frozen monthly P7 comparison.

**Rule changes.**

1. P8 is approved and active for one simulator-only daily opportunity pipeline using admitted
   point-in-time prices, volume, screens, earnings, corporate actions, macro context, and optional
   provenance-bound public headlines. Missing news is explicit and cannot be filled by the model.
2. The model may classify a bounded deterministic candidate set as ignore, watch, hold, or swing
   and may propose a price alert, horizon, thesis, and invalidation. Deterministic code owns the
   universe, ranks, validation, sizing, trigger evaluation, expiry, idempotency, execution, and risk.
3. P8 may add one isolated inactive simulator book, append-only assessment/alert tables, one daily
   scheduler, and one bounded read-only status route. Broker routes, credentials, real capital,
   leverage, shorting, options, arbitrary symbols, and same-bar fills remain forbidden.
4. A triggered alert is not an order. The model must reassess fresh retained evidence after the
   trigger; only an eligible swing decision may produce a capped next-session simulator order.
5. P8 may use staged commits during this explicit implementation goal, each under 1,500 inserted
   non-data lines, followed by full validation and independent evidence review.

**Ceiling changes.** P8 may add up to 1,400 lines under `server/`, 400 under `engine/`, and 100
under `sim/`. Ceilings become server 49,500, engine 11,800, and sim 7,100 lines.

## 2026-09-22 — Approve multi-cadence agents and a locked paper-trade tool

**Verdict.** The owner asked the always-on box to compare hourly, multi-hour, and nightly agents,
test distinct prompts and scales, provide an actionable tool-call path, self-test the entire flow,
and integrate an agent with an algorithmic candidate.

**Rule changes.** P9 is approved and active. Hourly and four-hour variants are observation-only;
one nightly policy may request a typed simulator trade through a locked, append-only, idempotent
consumer. The model never selects size or risk limits. The algorithm-plus-agent arm is veto-only.
All variants remain isolated from broker code and real capital, and their evidence cannot be pooled.

**Ceiling changes.** P9 may add 900 lines under `server/`, 250 under `engine/`, 150 under `sim/`,
and 150 under `tools/`. Ceilings become server 50,400, engine 12,050, sim 7,250, and tools 7,550.
