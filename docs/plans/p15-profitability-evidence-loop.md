---
plan: P15
title: Profitability evidence loop
status: approved
opened: 2026-09-25
owner_decision: approved 2026-09-25 (feedback.md); open inputs listed under "Owner inputs"
---

## Goal

Turn the AI decision loop from one nightly pick with no comparator into a system that answers,
within months rather than years, **whether the AI adds after-cost value over a deterministic rule**.
It also trades on fresher information. When this plan is done:

1. Every nightly candidate in a wider, long-usable universe carries a model score (probability and
   expected excess return) and a deterministic baseline score. Both are labelled, and a
   pre-registered paired test is coded and reported.
2. Three isolated simulator books with identical mechanics trade on those scores: AI-ranked,
   rule-ranked control, and rule + AI veto. They sit beside the untouched P8 v1 book.
3. Entries are protected by a deterministic limit-on-open for every P15 book, and by an AI pre-open
   reassessment that may only cancel.
4. The hourly and four-hour observers produce pairable evidence, and event-driven shadow triggers
   (news, SEC 8-K, intraday movers) produce labelled decisions within minutes of the information.
5. Every gate in this plan is code, not prose, and its status appears in the existing evaluation
   status read model and in one generated report.

The model proposes; deterministic code keeps data admission, universe, sizing, risk, fills,
accounting, and halts. Nothing in this plan grants broker access, credentials, real capital,
shorting, leverage, or intraday execution authority.

## Why now

Evidence from the 2026-09-25 review (live `/meta` 13:37 UTC and a code trace):

- **One actionable decision a night.** `engine/daily_opportunities.py` sets `MAX_CANDIDATES = 5`
  (and `detect()` caps `limit` at 20). Its `standout_score` is built from the *absolute* daily
  return and gap plus volume and RS, so about half the candidates are losers a long-only book
  cannot buy. The nightly v1 policy abstained on 92% of assessments.
- **No statistical power.** The P8 gate asks for 20 completed trades. At a per-trade standard
  deviation of ~12%, 20 trades detect only about 5% mean excess per trade; a realistic 1% edge
  needs about 500. At the current rate even 20 trades arrive around 2027-02.
- **Stale entries.** The nightly run decides at 02:00 UTC and the order fills at the next open,
  about 11.5 hours later, with no pre-open check. The first order (FSLY) gapped −6.2% between
  decision and fill.
- **Observer evidence is empty.** `server/hourly_opportunity_observer.py` skips the whole window
  when any one candidate lacks a fresh quote. One halted ticker voided all nine windows on
  2026-09-24, and v4 had 0 traces. Separately, `farm/agent_evaluation_analysis.py`
  (`_unique_by_key`) keys decisions by `(market_date, ticker, horizon)`, so seven hourly windows a
  day make every key ambiguous and it is dropped. Intraday labels
  (`server/agent_evaluation.py`, `label_after = observed_at.date()`) also enter one session later
  than nightly labels, so no pair ever matches.
- **No comparator.** The "gap-volume + AI veto" lane in `server/daily_opportunity_read_models.py`
  is recomputed for the latest run only. It has no book and no history.
- **Idle capital and arbitrary exits.** P8 sizes at 10% with at most 3 positions, so at least 70%
  of the book is always idle cash. The stop is the signal-day low, which sat 19% below entry on
  FSLY.
- **Unused inputs.** The host's RSS scraper collects 11 feeds every 10 minutes, and nothing reads
  it. The SEC 8-K capture is built but has no contact identity.

## Where this runs

Run on **the host**, in the live checkout (`$HOME/trading-engine`), where the DuckDB file, the
systemd user units, the model proxy, and the scraper output (`$HOME/news-scraper/data/news.jsonl`)
exist. W0 checks `systemctl --user` and the live database. If either is missing (for example, in a
laptop clone), do W1–W7 against fixtures and dry-runs, then stop before W8 activation and say so.

## Owner inputs

Defaults apply until the owner decides (see [`../product.md`](../product.md#open-owner-only)):

- `TRADING_ENGINE_SEC_USER_AGENT` unset → the 8-K trigger source reports `unconfigured`; the
  other sources run.
- Shorting stays forbidden → the universe is filtered to upside and trend names.
- P8 v1 keeps running unchanged as its own cohort, with its own book and gate.

## Frozen registration (fill in, commit, then never edit)

Before activating anything that produces evidence, write `server/p15-registration.json` holding
every value below plus the code identities, and commit it by itself. After activation, a change to
any value is a **new version with a new cohort**, never an edit. Values marked *(builder sets)*
are chosen once from engineering constraints, never from outcomes, and are recorded in the
registration and the BUILDLOG.

**Universe (nightly, deterministic, versioned `p15-universe-v1`):**
- A new function next to `detect()` (don't widen `detect()`, which P8 v1 depends on).
- Admissible: `MIN_CLOSE`, `MIN_HISTORY`, and the `MAX_ABS_DAILY_RETURN` rules from P8, plus
  median dollar volume ≥ US$20M and not quarantined. Median dollar volume is the median of
  close × volume over the 20 sessions before the market date (the same rows `_candidate_rows`
  uses for median volume).
- Composition:
  - **Up movers:** the top 40 by the existing standout score among names with `daily_return > 0`.
  - **Trend names:** the top 20 by RS rank among trend-template passers not already included.
  - Plus every name held by a P15 book (`held_only`). These are scored and drive exits but are
    excluded from the primary IC, because a book chose them.
  - Each candidate records its stratum: `mover`, `trend`, or `held_only`.
  - Order is deterministic, and the snapshot is retained.

**Model scoring policy (`p15-scoring-v1`):**
- **Output per candidate** (typed JSON, schema-validated):
  - `p_outperform_5`: probability that 5-session net excess vs SPY is > 0.
  - `expected_excess_bp_5` and `expected_excess_bp_10`.
  - `action` ∈ {`ignore`, `watch`, `buy_candidate`, `exit`} (`exit` only for held names).
  - `thesis` (≤ 60 words), `invalidation`, and `evidence_ids`.
  - No quantities, sizes, or limits.
- **Calls:**
  - Candidates go in chunks of *(builder sets, ≤ 15)* with a shared market-context block.
  - Each chunk runs with **k = 3 independent samples**. Candidate order is permuted per sample
    from a recorded seed.
  - Each field aggregates as the per-candidate median. Every sample is retained.
- **Failures:**
  - A failed or invalid chunk becomes explicit `unavailable` decisions for its candidates.
  - It is never retried with a different model or prompt.
- **Inputs, all availability-time bounded and each with a leakage test:**
  - Everything P8 already admits.
  - Retained headlines.
  - Admitted P15 event facts available before the decision time.
  - TradingView quotes may appear as model inputs; they never price a fill or set a limit.
- **Model identity:** the existing bound model identity. Drift fails closed.

**Deterministic baseline (`p15-baseline-v1`):** rank candidates by RS rank, highest first. A
missing RS rank ranks last. Ties break by standout score, then ticker. This is also the control
book's ranking.

**Labels:**
- Entry at the first session open after the decision's market date; exit at the close of the
  horizon session.
- 20 bp round-trip cost; excess vs SPY computed on the same basis.
- Horizons 1/5/10/20, unchanged.
- **Primary horizon: 5.**
- **Storage:** a new `agent_evaluation_labels_v2` table with a `label_basis` column
  (`next_session_open`, `next_bar`, `common_entry`, …). The existing `agent_evaluation_labels`
  (unique on decision and horizon) stays as is. Model and baseline scores and the stratum are
  stored in the decision payload.
- **Missing bars:** a name with a missing bar inside the horizon (halt or delisting) is labelled
  at its last available close, flagged, and included. It is never silently dropped.
- **Earnings gate input:** `unavailable` blocks entry; `no_upcoming_date` allows it.

**Primary test (the P15 verdict):**
- **Daily statistic:** each scored session gives
  `d_t = IC_model,t − IC_base,t`, where IC is the Spearman rank correlation between the score
  (`expected_excess_bp_5`, or the baseline rank) and the realised 5-session net excess, over that
  session's labelled candidates.
- **Session rules:**
  - Both ICs use the same candidates: `mover` and `trend` strata with a valid model score and a
    mature h5 label.
  - Ties take average ranks.
  - A session counts as *scored* only with ≥ 20 such pairs and neither score constant; others
    are recorded as `insufficient` with the reason.
- **Mean and standard error:** mean of `d_t`, with a Newey–West standard error at lag 4 (the
  horizons overlap).
- **Looks:** the test is taken only at 60, 90, and 120 scored sessions, each at one-sided
  α = 0.05/3.
- **PASS** at a look: the lower bound on mean `d_t` is > 0 **and** mean `IC_model` is > 0.
- **KILL:** at 120 sessions with no PASS, or at any look where the one-sided upper bound on mean
  `d_t` (α = 0.05/3) is < 0.
- **Reported, never gating:**
  - Brier score of `p_outperform_5` against climatology (the base rate over all prior mature
    labels) and against a logistic fit on the baseline rank. The fit uses an expanding window
    lagged 6 sessions.
  - IC by stratum (`mover`, `trend`).
  - A 5-bin calibration table.
  - Top-minus-bottom quintile net spread.
  - 10-session IC.

**Book mechanics (`p15-book-v1`, identical for all three P15 books except the AI pre-open cancel):**
- **Capital:** opening equity US$10,000. Uninvested equity is held in SPY in whole shares, so idle
  capital earns the benchmark.
- **SPY sleeve:** it sells at the same open that funds new entries and rebuys at the next open
  after exits. It stays invested through `risk_off`.
- **Fills and costs:** the existing simulator fill and cost model (`sim/fills.py`,
  `sim/execution.py`, liquidity-tier costs). The flat 20 bp applies only to labels.
- **Entry gates:** SPY above its 200-day average (`risk_on`), no earnings within 5 sessions, not
  quarantined. At most 8 names; at most 2 new entries per session.
- **Size:** 1% of equity at risk ÷ (2.5 × ATR(14) as a fraction of price), capped at 15% of
  equity per name. Use `sim/strategies/base.py::atr_wilder(..., period=14)`. Gross exposure is at
  most 100%: when cash (after selling SPY) runs out, lower-ranked entries are skipped and recorded
  as `insufficient_cash`.
- **Stop:** a close ≤ entry − 2.5 × ATR(14), fixed at entry, sells at the next open.
- **Time exit:** 10 sessions.
- **Entry orders:** limit-on-open at signal close × (1 + max(1.5%, 0.5 × ATR%)). The simulated
  fill price is the open plus modelled slippage. If that exceeds the limit, the order does not
  fill; it is recorded as `limit_not_reached` and gets a counterfactual label.
- **Kill (each book):** new entries halt at −20% drawdown from the book's peak equity. Exits
  continue.
- **Books:**
  - `p15_ai_ranked`: buys `buy_candidate` names with `p_outperform_5 ≥ 0.55` and
    `expected_excess_bp_5 ≥ 50`, highest expected excess first. It may exit a held name early on
    an `exit` action or a nightly `expected_excess_bp_5 < 0`.
  - `p15_rule_control`: buys the top baseline-ranked `mover` and `trend` candidates that pass the
    entry gates. Rule exits only. Its pre-open step is recorded as a no-op.
  - `p15_hybrid_veto`: the control's picks, skipping any that the model scores with
    `expected_excess_bp_5 < 0` (veto only). When the model score is `unavailable`, the pick is
    allowed. Rule exits only.

**Book comparison (secondary; required for promotion, never alone):**
- **Report after:** ≥ 90 calendar days and ≥ 30 closed trades per book. If a book has not
  reached 30 by the 120-session look, it is reported as `inconclusive`, and the book comparison
  is killed with the primary test.
- **Alpha:** the same one-sided α = 0.05/3 per look.
- **Test:** paired daily net return difference (AI − control and hybrid − control), with a
  Newey–West t-statistic, max drawdown, and turnover.
- **Promotion to a Stage 2 discussion needs:**
  - a primary PASS;
  - a book difference with a positive lower bound;
  - max drawdown no worse than −20% in each P15 book.

**Pre-open reassessment (`p15-preopen-v1`, AI and hybrid books only):**
- Runs at 09:05 America/New_York on sessions with pending P15 entry orders.
- Inputs: the nightly assessment, and headlines and event facts that became available since the
  decision. v1 has no pre-market price input: the admitted intraday source runs with
  `includePrePost: False`, and TradingView may not steer orders.
- Runs as its own timer, and must finish before 09:25 ET. A late or failed run means `keep`.
- Output per order: `keep` or `cancel` plus a reason. It can never add, resize, or reprice.
- Every cancelled order keeps a counterfactual label (the fill it would have had), so the
  cancel policy is scored separately. Report cancel hit-rate and the net bp saved or lost.

**Event triggers (`p15-events-v1`, shadow only, no order authority):**
- **Sources:**
  - Retained RSS headlines, ingested from `$HOME/news-scraper/data/news.jsonl` as bitemporal
    facts. Availability is the engine's ingest time; headline text only.
  - SEC 8-K filings via `tools/sec_edgar_capture.py` when the contact is configured.
    Availability is the retrieval time, not `acceptanceDateTime`.
  - An intraday mover scan at minutes :05, :20, :35 and :50 in regular hours (clear of the
    hourly and four-hour observers). It covers the P15 universe plus template passers
    (≤ 300 symbols). A mover means |return since prior close| ≥ max(4%, 2 × ATR%) and
    intraday relative volume ≥ 2. Intraday relative volume is cumulative volume ÷ (20-day
    median volume × elapsed fraction of the session).
- **Mapping:** deterministic, never by the model.
  - Headlines map by cashtag (`$TSLA`) or an exact match on the universe company name only.
    Unmatched headlines are retained unmapped.
  - Filings map by CIK.
- **Dedup:** at most one trigger per ticker per source per session.
- **Locking:** every P15 job takes the existing advisory lock and opens DuckDB the way the
  observers do. None is chained into `engine/run_daily.sh`.
- **Decision and labels:** the model returns the `p15-scoring-v1` schema plus `event_type`.
  Labels use two bases:
  - `next_bar`: the open of the first retained 5-minute bar after the decision. This is a new
    label basis version; existing labels are not mutated.
  - `next_session_open`: comparable with nightly decisions.
- **Latency:** record source availability → trigger → decision → label entry. Target p95 from
  trigger to decision ≤ 10 minutes, reported (not a gate).
- **Report:** event-decision IC and quintile spread on both label bases. Authority for events is
  a later plan.

## Scope

Work in this order. Each workstream ends with its tests, the full suite, a metrics snapshot, one
BUILDLOG v2 entry, and an independent review (see "How to run this plan").

**W0: Baseline and safety.**
- `git pull --rebase`, read the six contract files and this plan, then run
  `python -m tools.metrics_snapshot --dry-run`.
- Take and verify a recovery bundle before the first schema change.
- Record live timer health and the P8 v1 book state in the W0 BUILDLOG entry.

**W1: Observer evidence defects** (each gets a reproduction first). The fixed observers ship as
new variant versions and a new cohort; v1–v4 evidence is never rewritten.
- **Freshness:** per-candidate freshness in the hourly and four-hour observers.
  - Stale or halted candidates become explicit `unavailable` decisions.
  - The window runs if at least one candidate is fresh.
  - The unavailable ratio is persisted in the window result.
- **Pairing:**
  - Evaluation keys include policy variant and window.
  - Pairing compares each intraday window with the nightly decision on the same candidate
    `market_date`, from a common entry session: the later of the two label entries, under a new
    label basis version.
  - Primary pairing uses the first window of each day per variant; all windows is secondary.
  - Add fixture tests reproducing the 2026-09-24 ambiguity and the entry-day mismatch.
- **Veto lane:** delete the read-model-only gap-volume veto lane (P9 scope item 6) and its status
  fields; W3's hybrid book replaces it. Update any status consumer and UI panel that shows it.

**W2: Scoring policy and baseline.**
- Implement `p15-universe-v1`, `p15-scoring-v1`, and `p15-baseline-v1`.
- Write every scored candidate into the evaluation ledger as a decision row with its numeric
  fields and the baseline score.
- Add the leakage tests.
- Run it nightly from its own timer after the EOD pipeline, taking the advisory lock, and finish
  before 12:00 UTC. P8 v1 keeps its own 02:00 UTC run.
- Ship with a `--dry-run` that performs the whole flow against a copy of the database and
  writes nothing.

**W3: Comparator books.**
- Add `p15-book-v1` mechanics to the simulator:
  - SPY sleeve;
  - ATR sizing and stops;
  - limit-on-open entry (a new fill path in `sim/`, with tests showing a limit never fills
    above its price and never same-bar);
  - 10-session time exit.
- Create the three isolated books inactive, wire their consumers, and run a complete dry-run
  window.

**W4: Pre-open reassessment.**
- Add the 09:05 ET timer, `p15-preopen-v1`, and the cancel-only consumer.
- Add counterfactual labels for cancelled orders.
- Record decision → order → fill latency and implementation shortfall for every P15 order.

**W5: Event triggers (shadow).**
- Implement the three sources, the dedup, the trigger timer, the event decisions, both label
  bases, and latency capture.
- Rate-limit model calls: at most 60 event decisions per session day; excess triggers are
  recorded as `skipped_rate_limit`.

**W6: Gates and reporting.**
- Code the primary test, the book comparison, the pre-open scoring, and the event report.
- Code the **existing P8 evaluation rule exactly as P8 writes it**. The lower confidence bound is
  reported but is not a P8 gate.
- Add a trial-count register listing every policy version ever evaluated, so multiple testing
  stays visible.
- Extend `GET /agent/evaluation/status` with a `p15` section (no new endpoint).
- Generate `data/reports/agent-eval/p15.md` nightly.

**W7: Cleanup and docs (before activation, so registered code identities don't move after it).**
- Delete code, tests, and docs that P15 made dead.
- Leave no reference to removed lanes or stale versions outside `docs/history/`.
- Update `docs/how-it-works.md` (timers, runbook, and the P15 flow), `docs/scope.md` (including
  the active book count), `README.md`, and the metrics doc.

**W8: Activation.**
- Commit the frozen registration by itself.
- Pick an activation date: the next session at least one full dry-run day away.
- New units stay out of `AUTOSTART_UNITS` until the activation commit. Install them through
  `tools/install_automation.py`, then activate the books.
- Verify the first live nightly run, pre-open run, and trigger window end to end, and record the
  evidence.
- Final doc update, docs only: `docs/product.md` ("Where it stands", "Focus now", and the P15
  first look date) and `docs/plans/README.md` (P15 `active`).

**Follow-on, only after W0–W8 are done and green** (governed by their own approved plans; this
plan grants them nothing extra): P7 activation to its plan's "done when", then the P2 league
collapse.

## Not in scope

- Broker code, connections, credentials, real capital, shorting, leverage, options, margin.
- Intraday execution authority. Event triggers and observers stay shadow-only.
- Changing P8 v1, the P7 contract, the three frozen forward records, or any league book (except
  through P2's own plan). P15 supersedes P9 scope item 6 (the gap-volume veto lane) and changes
  P9's observers only as W1 states, as new versions.
- Tuning any registered value after activation, reusing labels to tune prompts, or pooling
  evidence across versions.
- Using TradingView data to price fills, set limits, or mutate operational prices. It may appear
  as a model input and a cross-check.
- Historical LLM backtests of P15 policies as promotion evidence (diagnostic only, P10 rules).
- New endpoints, dashboards, or operator CLIs beyond those named above.

## Done when

- `python -m pytest -q` passes in full, with the host's timezone and with `TZ=UTC`.
- `python -m tools.metrics_snapshot --check-budget` reports `ok: true` under the P15 ceilings.
- `server/p15-registration.json` is committed before the activation date, and the activation
  commit is later than it.
- Within 3 sessions of activation, `GET /agent/evaluation/status` → `p15` shows each of the
  following:
  - ≥ 50 scored candidates, each with model and baseline scores;
  - three P15 books active with correct opening equity;
  - a pre-open run record (or an explicit `no_pending_orders`);
  - ≥ 1 event-trigger window with a recorded latency;
  - hourly and four-hour windows with traces, and pairing counts > 0 in the paired metrics.
- `data/reports/agent-eval/p15.md` exists and shows the gate status as `collecting` with its
  next look date.
- An independent review of W1–W8 has no open correctness, leakage, or authority findings.
- `docs/product.md` and `docs/plans/README.md` show P15 as `active` (collecting), with the
  first look date.

## Budget

- **Ceilings** (raised by the 2026-09-25 feedback entry; caps, not targets):
  - server 54,450 (+2,500)
  - engine 13,750 (+1,000)
  - tools 8,450 (+400)
  - farm 12,550 (+700)
  - sim 7,900 (+500)
- Deleting P15-obsoleted code counts toward headroom. The doc-test ceiling is unchanged. Hitting
  a ceiling stops the session with a scope note; the builder never raises a ceiling.
- **Commits:** one logical step per commit, each under 1,500 inserted non-data lines, expected
  at 40–70 in total.
- **Sessions:** one long session may run the whole plan (see below). Several sessions are fine.
  Each resumes from the BUILDLOG, this plan's progress table, and the commit subjects.
- **Commit subjects** start with `P15 W<n>:` and name the step, so a restarted session can find
  its place.

## How to run this plan

This section overrides AGENTS.md's "one admitted item per session" and "do not loop" **for P15
only** (owner, 2026-09-25). Every other AGENTS.md rule still applies.

1. **Continue until done.** Work W0 → W8 in order without stopping between workstreams. Stop only
   when "Done when" holds, a stop condition fires, or a registered value would have to change.
2. **Use sub-agents freely.** Credit use is unconstrained. Use sub-agents for:
   - **parallel exploration:** tracing code paths before a workstream;
   - **drafting tests**, especially leakage and fill-path tests;
   - **independent review after each workstream.** Run at least three fresh reviewers:
     correctness and tests; look-ahead, leakage and label integrity; authority and safety (no
     path to broker, size, or real capital; fail-closed behaviour). Resolve every finding, then
     re-review until the reviewers are satisfied.

   **One writer rule:** only one agent edits the tree or writes to DuckDB at a time. Parallel
   editors use separate git worktrees and are merged one after another by the lead session.
3. **Prove by running.** Every workstream ends with its dry-run or live command and the salient
   output line in the BUILDLOG entry. Reading code is not proof.
4. **Keep production safe.**
   - Every commit reaches `origin/main` and the nightly pipeline pulls it. Keep every commit
     green and inert until W8: new books inactive, new timers not installed, and new code paths
     behind the dry-run or an explicit activation flag.
   - Never leave the tree dirty.
   - Take a recovery bundle before each schema change.
5. **Stop conditions.** Write one line under "Proposed, not approved" in `docs/scope.md` and stop
   if the work would need any of: broker access, credentials beyond the SEC contact, real
   capital, shorting, a ceiling raise, a change to P8 v1 or P7, or a registered value changed
   after activation. Model identity drift fails closed; it is not bypassed.
6. **Record progress.** Keep the table below current in each workstream's final commit, so a
   later session can resume.

## Progress

| Workstream | Status | Evidence (BUILDLOG date) |
|---|---|---|
| W0 Baseline and safety | not started | |
| W1 Observer evidence defects | not started | |
| W2 Scoring policy and baseline | not started | |
| W3 Comparator books | not started | |
| W4 Pre-open reassessment | not started | |
| W5 Event triggers | not started | |
| W6 Gates and reporting | not started | |
| W7 Cleanup and docs | not started | |
| W8 Activation | not started | |

## Risks

| Risk | Mitigation and rollback |
|---|---|
| Wider universe and k=3 sampling make the nightly run slow or flaky | Chunked calls with explicit `unavailable` outcomes; the run is idempotent per date; P8 v1 is untouched either way |
| Look-ahead through news, events, or labels | Availability-time cutoffs with a leakage test per input; a dedicated leakage reviewer each workstream |
| The scoring cohort is noisy and the IC test never passes | That is a valid answer. The KILL rule ends it at 120 sessions; the books and report remain as evidence |
| Limit-on-open misses the best winners | Recorded as `limit_not_reached`, with counterfactual labels; the same rule applies to every P15 book, so the comparison stays fair |
| Event triggers flood the model or duplicate nightly decisions | Per-ticker, per-source, per-session dedup; a 60-a-day cap; shadow only |
| A half-built change reaches the nightly pipeline | Inert-until-W8 rule; full suite before each commit; revert the commit on any producer failure |
| Budget pressure | Delete dead code first (the veto read model, superseded observer paths); stop at the ceiling |
