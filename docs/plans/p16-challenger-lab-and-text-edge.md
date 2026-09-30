---
plan: P16
title: Challenger lab, text edge, and evaluation science
status: active
opened: 2026-09-26
owner_decision: approved 2026-09-26 (feedback.md), including P15 remediation and activation as W0; optional inputs listed under Prerequisites
---

## Goal

Build the second layer of the [system blueprint](../system-blueprint.md) on top of P15. P15 answers
"does one model policy beat one rule?". P16 turns the engine into a **research lab** that tests
many well-defined hypotheses at once, on identical inputs, and judges them honestly. When this
plan is done:

1. **Evaluation science v2.** Every score is also judged after removing known factor exposure.
   Every challenger is monitored with always-valid sequential tests, and selection among
   challengers is deflated for the number of trials.
2. **Challenger lab.** Up to eight registered shadow challengers score the P15 universe every
   night beside the P15 champion. They cover company-name blinding, memory of the policy's own
   matured outcomes, a model tournament, an ensemble, and input ablations.
3. **Filing reader.** SEC 8-K earnings releases and other material filings are read within
   minutes of availability into structured, scored, labelled shadow decisions.
4. **Historical labs.**
   - **(a) Text lab:** a contamination-controlled historical test of the text signal, using
     time-locked language models whose training data ends before each test year.
   - **(b) Post-cutoff replay lab:** the frontier models paper-trade, day by day, the stretch of
     history after their own training cutoff, using point-in-time prices, news, and filings.
     They write post-mortems and running notes on their mistakes. This compresses months of
     forward evidence into days and tests whether the notes make the agent better.
5. **Portfolio construction v2.** A score-to-weights optimizer runs as a fair pair of shadow books
   (model scores vs rule scores) beside the P15 books.
6. **Execution realism.** The simulator's open fills are calibrated against retained intraday data,
   and a fill model v5 is registered for future cohorts.
7. **Operator digest and Stage 2 design.** A weekly one-page digest, and a design (docs only) for
   moving to personal hardware and IBKR paper.

No policy gains order authority from this plan. Promotion of any challenger is a later owner
decision based on P16's reports.

## Why now

- P15 produces one champion score and one rule score per candidate. The same candidates and labels
  can test many more hypotheses at almost no marginal cost, and credit cost is ignored
  ([`product.md`](../product.md)).
- The literature sets a low prior and names the traps:
  - News-based LLM signals decayed from a Sharpe of 6.5 (2021Q4) to 1.2 (2024) before costs
    (Lopez-Lira & Tang, arXiv:2304.07619).
  - Post-earnings drift is gone in large caps (Martineau, *Critical Finance Review* 2022).
  - Most LLM trading agents fail to beat buy-and-hold (StockBench arXiv:2510.02209; FINSABER
    arXiv:2505.07078).
  - Company knowledge distracts models, and blinding helps (Glasserman & Lin, arXiv:2309.17322).
- A factor-neutral, trial-counted, sequential evaluation is what separates a real edge from
  momentum exposure or a lucky variant.
- Time-locked models with published weights exist, and EDGAR filing history is free with
  acceptance timestamps. Together they allow the only honest historical LLM test available.
  Examples: ChronoGPT and ChronoBERT, yearly cutoffs 1999–2024, arXiv:2502.21206, weights at
  `huggingface.co/manelalab`; the instruction-tuned follow-up, arXiv:2510.11677.

## Prerequisites

- **P15 W0–W7 done** (they are, as of 2026-09-26). P15 W8 activation is **on hold** and moves
  into this plan's W0. W0 fixes the P15 review findings, issues the P15 registration again, and
  activates P15. After W0, P16 never edits P15's registered code paths. Later fixes become new
  P15 versions.
- **Owner** (already done: approval and ceilings, in the 2026-09-26 feedback entry):
  - optionally sets `TRADING_ENGINE_SEC_USER_AGENT` (without it, W3 builds and tests against
    fixtures and reports `unconfigured`);
  - optionally approves the `research-text` dependency group for W4a;
  - optionally creates free API keys (Alpaca, Finnhub, Alpha Vantage) for the W4b news archive.
    Free bulk archives and scraping run without them.
- **Where it runs:** the host, as in P15's "Where this runs".

## Frozen registration (fill in, commit, then never edit)

As in P15: write `server/p16-registration.json` with every value below and the code identities,
and commit it by itself before any P16 evidence is produced. Changes after activation are new
versions. Values marked *(builder sets)* are chosen once from engineering constraints and recorded.

**Evaluation science (`p16-eval-v2`, reporting; never changes P15's gates):**
- **Factor-neutral IC.** Each session, regress the realised 5-session net excess on these
  cross-sectional exposures over all labelled P15-universe candidates:
  - 12-1 month momentum;
  - 1-month return;
  - 1-day return;
  - log median dollar volume;
  - 60-session beta to SPY;
  - 60-session volatility;
  - sector dummies from `universe.sector` (missing → `unknown`).

  Report Spearman IC of each score against the residuals, next to the raw IC. Use numpy least
  squares; each exposure is winsorised at 1/99% and z-scored per session.
- **Sequential monitoring.** For each challenger against the champion, and the champion against the
  baseline, run a mixture sequential probability ratio test (mSPRT; Johari et al., *Operations
  Research* 2022) on the daily paired statistic `d_t` (as defined in P15).
  - Correct for overlapping horizons by using every fifth session. Report the other four offsets
    as a robustness check.
  - Mixing variance *(builder sets from the P15 pre-activation dry-run dispersion, recorded before
    any P16 label matures)*.
  - α = 0.05, always valid.
  - Lifetime allocation: `p16-challengers-f1` receives α = 0.04, so its fixed eight-member
    e-Bonferroni boundary is 8 / 0.04 = 200. The remaining α = 0.01 is reserved for exactly one
    future family containing `c-notes` and any later challenger; it receives a separate
    registration. Total lifetime FWER is at most 0.05.
- **Trial register and deflation.** Every policy version ever evaluated, in any plan, is one row.
  - Challenger ranking reports the deflated Sharpe ratio (Bailey & López de Prado 2014) of each
    challenger's long-top-quintile net excess series, using the register's trial count.
  - A challenger is flagged `candidate_for_promotion` only when its mSPRT against the champion
    rejects, **and** its deflated Sharpe probability ≥ 0.95, **and** its factor-neutral IC
    is > 0.
- **Transfer coefficient.** For every P15 and P16 book, report the correlation between the
  score-implied active weights and the actual active weights (Clarke, de Silva & Thorley 2002).

**Challenger lab (`p16-challengers-v1`, shadow only):**
- **Shared inputs.** Every challenger scores the same `p15-universe-v1` candidates from the same
  bundle, with the same output schema as `p15-scoring-v1`. Each changes only what its row says.
- **Budget.** At most 8 live challengers. Each is a new registered policy version and a trial
  register row. Failures become explicit `unavailable` rows.
- **Frozen family.** `family_id = p16-challengers-f1`, `M = 8`, with members in this order:
  `c-blind`, `c-memory`, `c-model-gpt-5.5-max`, `c-model-gpt-5.6-terra-max`,
  `c-ensemble`, `c-price-only`, `c-text-only`, `c-prompt-v2`. GPT-6-Astra is excluded because
  its company queue cannot satisfy the before-next-open deadline.
- **Shared metadata envelope.** Every family member receives the exact retained
  `p15-universe-v1` bundle plus the same cutoff-bounded company-name, alias, and sector envelope.
  The earnings `no_upcoming_date` correction is deferred to a separately registered universe-v2
  cohort so it cannot change only one side of this comparison.
- **Ensemble.** Mean all three numeric fields over the champion and the two `c-model-*` members.
  All three components are required; otherwise the row is `unavailable`. Choose action by
  deterministic majority, breaking ties with the component whose `expected_excess_bp_5` is
  nearest the fieldwise mean, and copy both text fields from the champion.
- **Epoch and prior.** After P15 supplies its first valid scoring origin, run the installed,
  timer-backed copied-store rehearsal under a temporary pre-registration. The literal epoch is
  the first NYSE session after the final W2 registration commit, written only after that rehearsal
  passes; then enable the W2 timer independently of later P16 activation. The prior is the exact
  `mixing_from_pre_activation([], [])` fallback because fewer than 20 eligible pre-activation
  origins exist; the registration records that reason.

| ID | Changes only | Hypothesis |
|---|---|---|
| `c-blind` | Tickers, company names, and names in headlines are replaced by stable per-session anonymous IDs. Sector and all numeric features are kept | Company knowledge distracts, or memorisation inflates, the champion |
| `c-memory` | Adds up to 20 of the champion's own past decisions whose h5 labels matured before the decision time, retrieved by the rule: same stratum, same sector, then nearest standout score. Each carries its thesis and realised outcome | Feedback from its own outcomes improves calibration |
| `c-model-<id>` (up to 3) | A different model identity available through the bound proxy, same prompt. The identity is bound and fails closed like the champion's | The decision-maker should be chosen on evidence |
| `c-ensemble` | No extra calls: the mean of the champion and all `c-model-*` scores | Averaging reduces noise |
| `c-price-only` | All text inputs removed | How much of the signal is text |
| `c-text-only` | Price and volume features removed; only text, sector, and earnings timing remain | Is the text signal separable |

- **Prompt v-next.** The champion's prompt is frozen. Every challenger uses a common, cleaner
  prompt revision (`prompt-v2`, fixing the issues recorded in the W0 prompt review). To keep the
  comparison fair, one extra challenger, `c-prompt-v2`, is the champion's model with `prompt-v2`
  and nothing else changed.

**Filing reader (`p16-filings-v1`, shadow only):**
- **Sources:** EDGAR 8-K filings with item 2.02 (results), 1.01, 2.01, 5.02, 7.01, or 8.01, for
  tickers in the P15 universe or the template passers. Text is the primary document plus exhibit
  99.1 where present. Availability is the retrieval time.
- **Poll:** every 5 minutes, 07:00–20:00 America/New_York on trading days, within SEC fair-access
  limits (≤ 10 requests/second, declared user agent).
- **Model output:** the P15 schema, plus these structured fields:
  - `event_kind`;
  - `guidance_change` ∈ {raised, maintained, lowered, withdrawn, none};
  - `headline_surprise` ∈ {beat, inline, miss, unknown};
  - `one_off_items` (list);
  - `tone` ∈ [−1, 1].
- **Labels:** `next_bar` and `next_session_open`, as in P15.
- **Latency:** retrieval → decision is recorded. Target p95 ≤ 5 minutes.
- **Report:** IC by `event_kind`, and the `guidance_change` and `headline_surprise` conditional
  means against their deterministic counterparts (e.g. the sign of the reported EPS change when it
  is extractable without the model).

**Historical text lab (`p16-textlab-v1`, research only, cannot promote):**
- **Corpus:** EDGAR 8-K item 2.02 filings 2015-01-01 → 2025-12-31 for every CIK that maps to a
  current or former listing reachable from the security master. Delisted filers are kept; their
  prices are used where the DB has them. Coverage is reported as survivor-biased where they are
  missing.
- **Availability (history only):** the EDGAR acceptance timestamp, the best available for past
  filings. Labels enter at the first session open after it.
- **Models:**
  - ChronoBERT or ChronoGPT embeddings from the checkpoint whose cutoff year is **before** each
    filing's year.
  - An expanding-window ridge regression, fitted only on filings whose 5-session labels matured
    before the test filing's date.
  - Ridge penalty *(builder sets by an inner time-series split on data before 2018, then fixed)*.
- **Outputs:**
  - yearly IC and quintile spread of the text score against 1/5/20-session net excess;
  - the same, factor-neutral;
  - the same for a `lookahead_control` run that deliberately uses the 2024 checkpoint for all
    years (expected to be inflated, which measures the contamination);
  - the frontier champion run on a blinded 2024–2025 subset, labelled contaminated.
- **Runtime:** CPU is enough for ~150M-parameter models. Dependencies (`torch`, `transformers`) go
  in an optional `research-text` group in a separate virtual environment, never in
  `engine/requirements.txt`, so the nightly is unaffected. Without owner approval of the group, W4
  stops after building the corpus.

**Post-cutoff replay lab (`p16-replay-v1`, research; can kill or deprioritize a policy, never
promote one):**
- **Window, per model identity:**
  - Start: the later of (the documented training cutoff + 60 days) and the first month in which
    the contamination probes pass.
  - End: the P15 activation date. After that, live evidence takes over.
  - Pin the model identity. If it drifts, that model's replay is void.
- **Contamination probes:** per month of the window, ≥ 50 dated public facts the model should not
  know, held out from prompts: index closes, earnings outcomes, and major headlines.
  - The month passes when recall accuracy is not above a registered guess baseline *(builder
    sets the baseline and threshold before running)*.
  - Where feasible, also run the lookahead-propensity check of Gao, Jiang & Yan
    (arXiv:2512.23847).
  - Results are published with the report.
- **Point-in-time data:** stored as a separate `historical_backfill` source; never mixed into
  live facts or the live ledger.
  - **Prices and features:** existing EOD bars. Screens, the P15 universe, and features are
    recomputed as of each replay date from bars on or before it. Names delisted inside the window
    are included where bars exist, and the missing share is reported.
  - **News, free sources first** (owner, 2026-09-26: any data now beats no data; scraping is
    allowed). Ingest every source below that works; don't wait for the best one.
    - **Priority 1, free bulk archives:**
      - GDELT 2.0 event and GKG files, every 15 minutes since 2015. Availability is GDELT's
        `DATEADDED`.
      - Common Crawl CC-NEWS (WARC, since 2016). Availability is the crawl timestamp.
      - SEC EDGAR full text. Availability is the acceptance time.
      - FNSPID (Dong et al., arXiv:2402.06698): headlines with dates and tickers. It is mostly
        before model cutoffs, so it serves the text lab and ticker mapping. Its day-only
        timestamps get a next-session entry.
    - **Priority 2, scraping** (respect `robots.txt`, rate-limit, identify the client):
      - press-release wires (GlobeNewswire, PR Newswire, Business Wire) via their archives and
        sitemaps;
      - company investor-relations news pages;
      - Yahoo Finance and Google News RSS for recent months;
      - Wayback Machine CDX captures of ticker news pages.

      Availability is the later of the page's stated publish time and the first independent
      capture time (for example, a Wayback or Common Crawl capture). When only a publish time
      exists, add a registered 15-minute lag.
    - **Priority 3, free API tiers** (the owner creates keys; the builder asks early and
      continues without them): the Alpaca news API (Benzinga archive), Finnhub company news, and
      Alpha Vantage news. Record each tier's history depth and terms in W4b's first commit.
    - **Mapping:** ticker tags where the source has them; otherwise cashtag, exact company name,
      or CIK, as in P15. Unmapped items are kept.
    - **Deduplication:** by normalised headline within 48 hours. The earliest available copy
      wins, and every copy is retained.
    - **Coverage report:** items per source, per month, per ticker decile of dollar volume, so
      thin coverage is visible, not silent.
    - **Privacy:** raw scraped text and transcripts stay on the host, outside git. The public repo
      gets only counts, hashes, and derived scores.
  - **Filings:** EDGAR acceptance timestamps.
  - **Earnings dates:** only as known before the replay date. Where the source cannot show that,
    the gate uses the actual date and the report flags it.
- **Replay engine:**
  - Steps session by session in replay time.
  - At each session's decision time it builds the P15-identical bundle as of that moment and
    calls the model with the registered prompt.
  - Writes to an isolated replay store (a separate DuckDB file). A label becomes visible only
    once the replay clock passes its horizon.
  - Runs the P15 book mechanics on isolated replay portfolios.
  - The same harness replays every challenger, and it is the standard onboarding test for any
    new model identity. Each model gets its own window from its own cutoff.
- **Mistake notes (`c-notes`):**
  - **Post-mortems:** after each replay session, the model writes a structured post-mortem for
    every decision whose label matured by that replay date. Each records what it expected, what
    happened, and one error type from a fixed taxonomy: `gap_risk`, `headline_overweight`,
    `sector_move_missed`, `earnings_surprise`, `regime`, `data_issue`, `noise`, `correct`.
  - **Notes file:** once a replay week, the model rewrites a running notes file of at most 1,500
    tokens from the post-mortems. Later sessions receive it in their prompt.
  - **Retention:** post-mortems and every notes revision are stored append-only by replay date,
    so each decision traces to the exact notes it saw.
  - **Comparison:** `c-notes` runs against the same model without notes on the same dates.
- **Development and lockbox:**
  - The first two-thirds of each window is development. Prompts, the notes design, and challenger
    choices may iterate there, and every iteration is a trial-register row.
  - The final third is a lockbox, run **once** per frozen policy version after development ends.
  - Report the lockbox results with the trial count.
- **Report** `data/reports/research/replay.md`, covering per policy and model:
  - IC, raw and factor-neutral;
  - book results;
  - notes vs no notes;
  - error-type frequencies over time;
  - lockbox results;
  - probe results.
- **Authority:**
  - Replay never promotes.
  - A lockbox IC whose upper bound is < 0 is grounds for the owner to kill or deprioritize that
    policy.
  - After its lockbox run, a live `c-notes` challenger may be registered in the challenger lab,
    starting from the notes as they stood at the end of the lockbox and updating them from live
    matured labels. The challenger cap becomes 9.

**Portfolio construction v2 (`p16-construct-v1`, two shadow books):**
- **Alpha per name:** α_i = IC_trail × σ_i × z_i (Grinold–Kahn).
  - `z_i` is the per-session z-score of the policy's score.
  - `σ_i` is the 60-session residual volatility.
  - `IC_trail` is the policy's own trailing 60-session mean IC from mature labels, floored at 0.
    Zero alpha means hold the SPY core.
- **Weights:** maximise α'w − λ·w'Σw − κ·|Δw|₁, with:
  - Σ a Ledoit–Wolf-shrunk 120-session covariance (numpy);
  - long only, per name ≤ 10%, sector ≤ 30%;
  - portfolio beta to SPY in [0.8, 1.1], with the remainder in the SPY core;
  - κ = the fill model's cost per unit turnover;
  - λ *(builder sets so that median ex-ante tracking error vs SPY is 4–6% annualised on the
    pre-activation dry-run, then fixed)*.

  Solve by projected gradient in numpy; no solver dependency.
- **Books:** `p16_construct_ai` (champion scores) and `p16_construct_rule` (baseline scores).
  - Identical mechanics otherwise: P15 fills, limit-on-open, costs, US$10,000, and a −20%
    drawdown entry halt.
  - Rebalance nightly with a no-trade band of 0.5% per weight.
  - Report both against each other, SPY, and the P15 books.

**Execution realism (`p16-fills-v1`, research; the new model applies to future cohorts only):**
- **Data:** for every P15 order and a registered random sample of 20 candidates a day, retain the
  first three 5-minute bars (TradingView and the admitted intraday source, research only), and
  compare them with the simulated fill. Compute the open-to-first-bar VWAP gap and the spread
  proxy by liquidity tier.
- **Fill model v5:** fit tier costs and gap slippage on data up to a registered cut date. Validate
  on the later data. Register v5 for future cohorts only; existing books keep v4.

## Scope

Work in order. Each workstream ends as in P15: tests, the full suite, a metrics snapshot, one
BUILDLOG v2 entry, and at least three independent reviewers (correctness; look-ahead and label
integrity; authority and safety).

- **W0: Baseline, P15 remediation, and P15 activation.**
  - Take a recovery bundle.
  - Fix every item in "P15 remediation before activation" below, with a reproduction or failing
    test first for each.
  - Issue the P15 registration again: a new `registration_revision`, the reason, and the new code
    hashes. This is allowed only because P15 has produced no evidence yet. If P15 has already
    activated when this session starts, the fixes become P15 v2 versions and a new cohort
    instead.
  - Run the whole suite under the host timezone and `TZ=UTC`, and do a fresh dry-run day.
  - Run the refine gate (see "How to run this plan") on the P15 registration and the fixed
    modules.
  - Then complete P15 W8 exactly as P15 describes: activation commit, `AUTOSTART_UNITS`, and
    first-cycle verification. Mark P15 `active` in its plan and the plan table.
  - Run a **prompt review** of every live model prompt, and write findings into
    `docs/design/prompt-review.md`. These feed `prompt-v2`; live prompts are not edited.
  - Record the P15 pre-activation dispersion that the mSPRT mixing variance needs.
  - Fold "P15 follow-ups" below into the P16 workstreams named against each item.
- **W1: Evaluation science v2** in `farm/`: factor-neutral IC, mSPRT, trial register and deflated
  Sharpe, transfer coefficient. Tests use synthetic series with known answers (for example, a
  score equal to momentum must show ≈ 0 factor-neutral IC).
- **W2: Challenger lab.** A generic challenger runner that shares the P15 bundle, the registration,
  and the eight challengers. It runs from its own timer after the P15 nightly scoring, with the
  advisory lock. Include a dry-run.
  - Before any W2 evidence, freeze `family_id`, the exact member list `M`, the epoch, and the prior
    mixture in the W2 registration. `M` fixes the e-Bonferroni threshold.
  - A daily pre-entry job must call `load_origin` → exposure snapshot → `evaluate_origin` →
    `record_origin_decision` for every family member before the next open. Set the epoch only after
    this job is timer-backed and has passed a dry-run. A missed-session test must show the resulting
    report state; gaps are never silently backfilled onto the fixed grid.
- **W3: Filing reader**, with a fixture-based suite and live activation only if the SEC contact is
  set.
- **W4: Historical labs.**
  - **(a) Text lab:** the corpus builder (resumable, checkpointed like P14), the time-locked
    scoring, and the report `data/reports/research/textlab.md`.
  - **(b) Replay lab:** the historical backfill sources, the contamination probes, the replay
    engine and isolated store, the mistake notes, the development and lockbox runs for the
    champion and at least `c-notes`, `c-blind`, and one `c-model-*`, and
    `data/reports/research/replay.md`.
- **W5: Portfolio construction v2**: the optimizer, the two shadow books, and a dry-run. Add the
  transfer-coefficient producer for P15 and P16 books, using active-return standard deviation for
  sigma and excluding SPY. When known-sector coverage is below 80%, cap all stocks at 30% combined.
- **W6: Execution realism**: capture, calibration report, fill model v5 registration.
- **W7: Operator digest.** A weekly generated `data/reports/weekly/<YYYY-MM-DD>.md`, one page,
  covering:
  - gate status and next look dates;
  - books against their controls;
  - challenger leaderboard with deflation;
  - filing reader and event activity;
  - fill-quality drift;
  - producer health;
  - anything that needs the owner.

  Generate it Sunday after walk-forward.
- **W8: Stage 2 design** (docs only; no broker code, credentials, or connections):
  `docs/design/stage2-broker-paper.md`. It covers:
  - what moves to a personal host and how (packaging, config and secret separation, data sync);
  - how the existing inert IBKR adapters would be exercised against a paper account;
  - reconciliation against the simulator;
  - loss limits and halts;
  - model identity for real capital;
  - a draft execution-layer plan, filed as `proposed`.
- **W9: Cleanup, docs, activation.**
  - Activation is staged per component: W2 activates independently after its timer-backed
    rehearsal and final family registration; W9 activates the remaining eligible P16 components.
  - Before enabling W6 capture, run a 09:46 ET delayed-data dry-run with at least one opening-bar
    miss; prove the 10:00/12:00 retries recover 09:30, keep the first valid capture, and count any
    still-missing selected names without replacement.
  - Retire the doc-pinning tests (`tests/test_docs*.py`), carried over from the closed P1, and
    split `docs/how-it-works.md` into an ops runbook and an architecture reference.
  - Delete P16-obsoleted code before activation.
  - Update `system-blueprint.md` (layers table), `product.md`, `how-it-works.md`, and `scope.md`.
  - Run the refine gate on the P16 registration and each new module before the registration
    commit.
  - Remove the extra, unregistered champion factor-neutral mean-IC promotion check from the P16
    sequential/report path; do not add it to the registration.
  - Validate that every report row's factor-neutral policy is its challenger and that the champion
    factor-neutral policy is `p15-scoring-v1`.
  - Before sequential evaluation consumes a stored factor report, recompute it from its stored
    inputs and require an exact match.
  - Isolate the P16 status projection so its validation errors cannot make P15 status return 503.
  - Wire the primary kill status through a P16 adapter only; do not edit P15 registered files.
  - Queue recovery-detected W5 exits in the recovery window itself, with a behavioural test. The
    accepted W5 checkpoint instead queues them for the next constructed window, a bounded deviation
    from the evaluation design during outage recovery.
  - Guard W5 `process_through` so it recovers only sessions whose construction deadline has passed.
  - Derive the W5 recovery cutoff from the price-fetch schedule, or skip recovery cleanly when that
    day's close has not been fetched, instead of silently missing stops.
  - When W6 writes its 80 literal activation sessions, accept the `sessions` field in the loader
    and restore the 80-session exchange-calendar contiguity check.
  - Pass W6 bar-capture `attempts` per scheduled capture time (09:46, 10:00, and 12:00), rather
    than as one undifferentiated schedule value.
  - Compute W6's cross-source opening gap in one place.
  - Exercise a parsed noon W6 response in the delayed-data rehearsal, not only a `BAR_COUNT`
    marker.
  - Before W5 activation, freeze the cohort minimum and construction registration binding in the W9
    registration.
  - Before any W4 producer runs, require the owner's SEC contact and record the price archive's
    listing date in the registration. The W4 reports must state the accepted survivorship,
    conservative entity-mapping, and CC-NEWS sidebar limits.
  - Treat splitting `farm/replay/sources.py` as cleanup only; its current size is not an activation
    blocker.
  - Fix the seven pre-existing non-UTC tests at `tests/test_p15_evaluation.py` lines
    489/545/637/665/744/767/794 when the fix is outside P15's registration closure; otherwise
    document why they remain. Every checkpoint also runs the full suite under `TZ=Asia/Singapore`.
  - Commit the registration by itself, activate on a date at least one dry-run day away, and
    verify the first live cycle of each new producer.
- **W10: Final refine pass.** After activation, run the refine loop on each written deliverable:
  `system-blueprint.md`, `product.md`, the text lab and replay reports, the first weekly digest,
  and `docs/design/stage2-broker-paper.md`. Registered code is out of bounds here.

## P15 remediation before activation

From three independent reviews of P15 at `edf7f05` (spec conformance; look-ahead and statistics;
safety and operations), run on 2026-09-26. File references are as of that commit.

| # | Problem | Required fix |
|---|---|---|
| R1 | `farm/p15_event_runner.py` (~754–784) holds the DuckDB writer through every model call, for up to 14 minutes. The hourly and four-hour observers, the TradingView slice, and the API (`wait_s=0`) fail during those windows, which brings back the empty-window defect | Open, write, and close around each model call, as the scoring runner does |
| R2 | `server/p15_scoring_runner.py` connects with `wait_s=0` and catches only connector and validation errors. Contention with P8 (02:00–02:30 UTC) leaves a run stuck at `running`, and the persistent timer never retries | Bounded waits, catch `duckdb.Error`, write explicit `unavailable` rows, and let a retry resume the same date idempotently |
| R3 | A late scoring run can see post-entry news. The run only refuses after 12:00 UTC on its own day and takes `latest_operational_market_date`. Suppose the timer fires on D+2 while D+1 coverage is low: it scores D with news up to D+2, labelled and filled from D+1's open | Refuse unless the start is after D's close and before 09:30 ET on `next_session(D)`; record the refusal as a failed run; add a test |
| R4 | `engine/bitemporal_facts.py` (~128) keys replays by availability and ingest time, so every refetch creates a new revision. `engine/p15_event_sources.py` (~385) then fires old 8-Ks (and repeated RSS guids) as new triggers, which would eat the 60-a-day cap once the SEC contact is set | Trigger only on a fact's first availability (no earlier row with the same `normalized_sha256`); for 8-Ks, also require acceptance after the previous scan |
| R5 | The nightly scoring input hard-codes `"event_facts": []` (`server/p15_scoring_runner.py` ~125; `tests/test_p15_scoring.py` ~172 pins it), though the registration lists admitted event facts as an input | Pass availability-bounded event facts; replace the pinning test with a leakage test |
| R6 | Missed sessions fill at the wrong open. If a scoring run fails, the next `process_pending` (`sim/p15_books.py` ~627) fills older intents at a later open, and skips stops and time exits for the missed closes | Process book windows session by session from the last `p15_book_windows` row; expire entry intents older than one session as `stale_signal` |
| R7 | The primary test's standard error is too small. Bartlett weights at lag 4 under-count a 5-session overlap, and normal critical values at n = 60 compound it; the real one-sided α per look may be about 4%, not 1.67%. The only test compares against the same formula (circular) | Use the uniform (Hansen–Hodrick) kernel at lag 4, falling back to Bartlett at lag 8 if the variance is not positive, with t critical values (df = n − 1). Add a hand-computed known-answer test and a simulation: under the null, false passes across the three looks ≤ 5%; a planted IC passes. Record the change in the re-issued registration |
| R7b | **Supersedes R7's fix (added 2026-09-27, before activation).** Two independent 40k–100k-path simulations show that the R7 fix as written (uniform kernel at lag 4, t with df n − 1) still gives about 6.2% three-look false passes under Gaussian MA(4) and 7.4–7.5% under IID. The lag-4 variance has only about 7 effective degrees of freedom at n = 60 | **The lead re-issues the P15 registration before activation** with the primary test as a **non-overlapping offset-0 t-test**: every 5th scored session, df 11/17/23 at the 60/90/120 looks, one-sided α = 0.05/3 each (≈3.3–3.4% three-look size; power ≈86.5% vs 89.1% at a 0.03 gap). The lag-4 variance becomes a reported diagnostic. Skips decided before outcomes are seen (fewer than 20 candidates, or constant scores) are allowed. State that persistent AR-type dependence is outside the guarantee. Paste-ready text will be at `~/.tae/out/p16-design-eval/r7-registration.md` once that design session's round 2 lands |
| R8 | A missing-bar label is written as soon as SPY reaches the horizon, even when the ticker's bar is merely late. It is then permanent (`server/agent_evaluation.py` ~440–470), and the missing-entry path stores a net excess of 0 against a net return of −20 bp | Label at the last close only after a later bar for that ticker exists or a fetch attempt for the date is recorded, with a 3-session grace period; make the fields consistent |
| R9 | Nothing enforces the frozen registration. Thresholds are duplicated as literals (for example `sim/p15_books.py` ~330) | Add a test that checks every registered constant and every registered file hash against the code, so a post-activation edit fails CI |
| R10 | The pre-open run has no session check (`server/p15_preopen.py` ~319); on holidays it can cancel orders a day early | Return `not_session` on non-sessions |
| R11 | `_p15_atr` (`engine/daily_opportunities.py` ~34) lacks the `REAL_BAR_SQL` filter and duplicates `atr_wilder` | Reuse `atr_wilder(..., period=14)` over real bars only |
| R12 | One missing mature label anywhere marks the whole test `invalid` (`engine/p15_evaluation.py` ~311/329), including rows the test never uses | Count only rows the test uses, with a grace period after maturity |
| R13 | Look results are recomputed every run | Persist each look's result the first time it is reached (append-only, hashed) so the verdict is tamper-evident |
| R14 | The public report `data/reports/agent-evaluation.json` carries internal runtime strings ("internal edition" CLI identity), against the public-hygiene rule | Publish a runtime identity hash instead; keep the literal in the private database |
| R15 | The W8 rehearsal logged 17 model calls where 60 candidates in chunks of 10 with k = 3 means 18, and reported no unavailable count. `docs/how-it-works.md` (~1504) still says the P15 units are absent | Explain the count on the new dry-run and record `unavailable_count`; fix the doc |
| R16 | The scoring prompt doesn't say that a negative `expected_excess_bp_5` exits a held name in the AI book | Add one sentence before the registration is issued again |

## P15 follow-ups (after activation, as new versions; fold into the named workstream)

| Item | Where |
|---|---|
| Screen results have no availability bound (`daily_opportunities.py` ~321 takes the latest `run_date`); store and filter on compute time, and flag `screen_date != market_date` | W1 |
| `next_bar` falls back to the prior close when no later bar exists; exclude or flag those labels in the event IC | W1 |
| Label dates taken from UTC (`observed_at.date()`, `decision_at.date()`) should use the New York date | W1 |
| Counterfactual labels mix cost bases (modelled fill vs flat 20 bp for SPY); use one basis | W1 |
| `observer_pairing` counts every window; make the first window of each day primary, as the spec says | W1 |
| `books()` reports `killed` only when eligible; kill the book comparison with the primary test | W1 |
| The Brier comparisons use different samples, and the logistic lag counts dataset sessions; align the samples and use market sessions | W1 |
| The P8 rule counts traces, not market sessions, and omits the metrics P8 lists | W1 |
| Earnings: a snapshot with only past dates should be `no_upcoming_date` (allow), not `unavailable`; add an `as_of` staleness limit | W2 (as `p15-universe-v2`) |
| Mover relative volume assumes a 390-minute day on early closes; company-name matching ignores case | W3 |
| The hybrid book fills a vetoed slot with the next-ranked name; record it explicitly in the registration | W0 (registration text only) |
| `agent-cadence-registration.json` renamed the v4 observers to v5 instead of adding v5 alongside them; restore v4 as retired entries | W0 |
| The laptop lint commit `61b6a26` touched P8 v1 files; prove it preserves behaviour by replaying the last P8 run bundle (identical output) and running the P8 tests | W0 |
| The model identity is an unversioned catalogue alias; show that prominently in every report | W7 |
| `tools/sec_edgar_capture.py` (~132) parses the submissions-JSON `acceptanceDateTime` (`...Z`) as UTC. Reviewers report that its wall clock is often US Eastern. Verify, and if so read `ACCEPTANCE-DATETIME` from the filing index or header as America/New_York, as a versioned P15 follow-up (see the filings design folder, `repo-followups.md`) | W3 |

## W11: end-to-end synthetic proving ground (owner request, 2026-09-27)

Once W9's fixes land, test the whole AI decision pipeline on **mock data with known answers**,
then run evaluation loops on the agent.

- **Synthetic world:**
  - Fictional tickers and companies, so the model can't have memorised them.
  - Hundreds of sessions of prices, headlines, and 8-K-style filings generated from a registered
    seed.
  - **Planted signals** with known IC, in difficulty tiers:
    - *easy*: an explicit guidance raise or cut;
    - *medium*: numbers in a filing that need arithmetic;
    - *hard*: interactions and sector context.
  - Pure-noise features alongside the signals.
  - **Traps**: facts timestamped after the decision (look-ahead bait), look-alike famous names,
    stale quotes, halted tickers.
- **Controls first**, deterministic stub models:
  - an *oracle* must recover the planted IC within tolerance;
  - *random* must show no effect;
  - *inverted* must flip the sign.

  This proves the full W1 statistics and reporting path measures what it claims before any
  real model is judged.
- **Real-agent runs:** the P15 champion and the W2 challengers score the synthetic world through
  the real code paths (scoring, books, labels, W1 evaluation, reports) in an isolated store.
  Report:
  - recovered IC by tier;
  - calibration;
  - the trap hit-rate (any look-ahead use is a defect in the plumbing or the prompt);
  - an error taxonomy.
- **Fault injection:** missing data, halted tickers, model outage, late runs. The expected
  behaviour is explicit `unavailable` rows and no orders.
- **Evaluation loops:**
  - The orchestrator reviews each run, chooses prompt or policy changes, re-runs, and compares.
  - Every variant is a trial-register row, even in the sandbox.
  - At most 3 rounds per question.
  - Improvements that pass become *proposals* for new registered versions. They never change a
    live registration.
- **Isolation:**
  - a separate DuckDB file and no timers;
  - results labelled `synthetic`, never pooled with real evidence;
  - no promotion authority.
- **Design input:** `~/.tae/out/p16-design-proving-ground/` (written by a parallel design
  session). The lead builds from it after W9; the orchestrator reviews the design and each run.

## Not in scope

- Order authority for any challenger, filing decision, or construction book beyond its isolated
  shadow simulator book. No change to P15, P8, P7, or frozen records.
- Broker code, connections, credentials, real capital, shorting, leverage, options.
- Fine-tuning any model on the engine's labels.
- Changing a live prompt in place. A prompt change is a new version.
- Using the historical text lab or any pre-cutoff result to promote a policy.
- New endpoints beyond extending `GET /agent/evaluation/status` with `p16` and the digest file.

## Done when

- The full suite passes under the host's timezone, `TZ=UTC`, and `TZ=Asia/Singapore`, and
  `tools.metrics_snapshot --check-budget` is ok.
- `server/p16-registration.json` is committed before the activation commit.
- Within 3 sessions of activation, `GET /agent/evaluation/status` → `p16` shows:
  - every registered challenger with ≥ 50 scored candidates a session (or explicit `unavailable`
    rows);
  - both construction books active;
  - factor-neutral IC and mSPRT state for each challenger;
  - the trial count.
- The filing reader has processed ≥ 1 live filing, or reports `unconfigured`.
- `data/reports/research/textlab.md` exists with yearly results and the look-ahead control, or
  states that W4 stopped at the corpus pending the dependency decision.
- `data/reports/research/replay.md` exists with probe results, development and lockbox results for
  the champion and `c-notes`, and the news source used.
- The first weekly digest exists.
- `docs/design/stage2-broker-paper.md` exists, and the draft execution plan is `proposed`.
- P15 is active, with registration revision 3, and R1–R16 are closed, each with its test.
- Independent reviews of W0–W9 have no open findings.
- Every refine gate and the W10 refine pass ended with an eligible version scoring ≥ 8/10. The
  final BUILDLOG entry carries the table of versions and scores, or explicitly lists what fell
  short and why.

## Budget

- The owner removed the per-layer LOC ceilings on 2026-09-27. Code size remains visible in the
  metrics snapshot, but it does not gate this plan.
- The per-commit 1,500 inserted non-data line cap, BUILDLOG entry budget, doc-test freeze, and
  same-change deletion of code made dead remain binding.
- W4 code lives under `farm/textlab/` and `farm/replay/` and counts toward farm.
- **Commits:** subjects start with `P16 W<n>:`, each commit under 1,500 inserted non-data lines,
  expected at 60–100 in total.

## How to run this plan

The P15 run contract applies unchanged (continue until done, sub-agents allowed, single writer,
prove by running, inert until activation, stop conditions, progress table). Additions:

- **Model effort.**
  - Run the lead session at the highest reasoning setting. W1, W4, and W5 are statistics-heavy,
    and a subtle leakage or selection error invalidates months of evidence.
  - Sub-agents doing mechanical work (fixtures, corpus crawling, docs) may run lower.
  - Every reviewer runs at the highest setting.
- **Use the context window.** Load this plan, the blueprint, P15, `product.md`, `AGENTS.md`, and
  the P15 evaluation and scoring modules at the start of each workstream, rather than rediscovering
  them through search.
- **Refine loop.** Use the `refine` skill: in the store at `.claude/skills/refine/`,
  and publicly at
  [ong6/skillpack `skills/refine`](https://github.com/ong6/skillpack/tree/main/skills/refine).
  If the skill is not installed, follow that file.
  - Fresh reviewer sub-agents with no inherited context score the artifact against a rubric they
    choose in round 1, then freeze it.
  - The brief's hard constraints are this plan's registered values and the AGENTS.md absolute
    rules. A reviewer suggestion that breaks one is declined and noted.
  - Threshold 8/10, at most 3 refinement rounds, each changed version re-reviewed.
  - Keep the best eligible version.
  - Before activation, the loop may change code. After activation, it may change only docs and
    reports.
- **Ask for decisions early.** Write a one-line entry under "Owner inputs needed" in the progress
  table the moment a decision blocks progress, and continue with the next unblocked workstream.

## Progress

| Workstream | Status | Evidence (BUILDLOG date) |
|---|---|---|
| W0 Baseline, P15 remediation (R1–R16), P15 activation | **registration revision 3 activated 2026-09-29; revision 4 label-validator fix ready for deployment; first-cycle verification remains due through 2026-10-01**. A fresh 90-table recovery bundle verified; all three books activated at the common 2026-09-28 checkpoint; and the three installed timers are enabled and systemd-verified. Lead: `p16-sol-lead` (GPT-5.6-Sol) | 2026-09-30 |
| W1 Evaluation science v2 | complete; accepted core, durable evidence, family report, and existing-status-surface projection are verified. W9a adds the isolated status adapter and loads the accepted 103-row P5–P16 census with exact trial contribution N=139 | 2026-09-28 |
| W2 Challenger lab | staged; implementation and inert timer complete, while the first P15 origin gates the timer-backed rehearsal, literal epoch, final family registration, and independent activation | |
| W3 Filing reader | complete and inert; W9a verified first-fetch baselines, unchanged-response receipt reuse, the host-wide dispatch lock, short scan callbacks, prior-session queue sweeping, per-leg next-bar basis checks, and P15/template-only liquidity. The scan orchestrator derives its gate from the SEC caller inventory and remains blocked while frozen P15 uses direct transport | 2026-09-28 |
| W4 Historical labs (text lab, replay lab) | complete and accepted for code; real-data producers remain inert until W9 records the price-archive listing date and the owner supplies the SEC contact. Accepted limits are registered for W9 reporting; the post-cutoff grid remains planned pending probe admission | 2026-09-28 |
| W5 Portfolio construction v2 | complete and inert; W9a recovery now waits for the missed window's NYSE-open construction deadline, uses the first completed P15 EOD fetch batch as its information cutoff, skips when a held close was not available by that cutoff, and queues detected exits into that recovery window | 2026-09-28 |
| W6 Execution realism | complete and accepted, inert: every selected name retains its best-attempt measurement and as-of liquidity tier even when bars fail, so valid quote targets and honest tier coverage survive; `baseline_v1` is unchanged | 2026-09-28 |
| W7 Operator digest | complete: Sunday post-walk-forward composer produces the compact weekly gate/book/challenger/activity/health view with explicit unavailable states and the unversioned-catalogue-alias warning | 2026-09-28 |
| W8 Stage 2 design | complete: accepted design filed with binding review notes; P17 is indexed as proposed and grants no broker, credential, account or capital authority | 2026-09-28 |
| W9 Cleanup, docs, refine gate, activation | W9a complete: timezone, W1, W5, inert W3 fixes, the accepted P5–P16 canonical census (103 rows; N=139), prose-test retirement, the operations/architecture split, and P16 state documentation are complete. W9b retains registration, rehearsals, and activation. Production connection portability and the scheduled P15 direct SEC caller remain frozen inside the P15 registration closure | 2026-09-28 |
| W10 Final refine pass | not started | |
| W11 Synthetic proving ground and evaluation loops | design in progress (`p16-design-proving-ground`) | |

The orchestrator raised W4's production-Python allocation to 5,000 lines. Owner input remains
optional for the `research-text` dependency requested 2026-09-26, so W4 uses the reduced text-lab
variant. SEC contact and free API keys retain their stated defaults.

**Design inputs (parallel GPT-6-Astra design sessions, started 2026-09-27).** Three sessions write
specs, test vectors, and numpy reference drafts on the host, outside the repo. Before building a
workstream, the lead reads its folder. When the folder's `STATUS` says `done`, treat its `spec.md`
as the starting design. Registered values stay the lead's decision, and must be recorded before
activation. If a folder is not done yet, start the workstream anyway and merge the spec in when it
lands.

| Workstreams | Folder on the host |
|---|---|
| W1, W5 (and a check of R7) | `~/.tae/out/p16-design-eval/`: **conditionally accepted 2026-09-27** after 3 rounds (spec v3: statistics 8.9, buildability 7.8). W1/W5 must meet the **2 mandatory build conditions** in `ORCHESTRATOR-ACCEPTANCE.md` in that folder (solver convergence under the extended stress test; the limit-attempts table mapping). Note: `baseline_rank` is ascending, so the rule score is −`baseline_rank`. `r7-registration.md` is the R7 text |
| W4a, W4b | `~/.tae/out/p16-design-replay/`: **conditionally accepted 2026-09-27** after 3 rounds (spec v3: statistics 7.3, buildability 8.3). W4 must meet the **4 mandatory build conditions** in `ORCHESTRATOR-ACCEPTANCE.md` in that folder (notes filter, lockbox tag, split knowledge clock, price series per consumer), each with tests, and the orchestrator reviews the W4 checkpoint before any W4 producer runs |
| W3, W6, W8 (full Stage 2 draft) | `~/.tae/out/p16-design-filings-stage2/`: **accepted 2026-09-27** (independent review round 2: spec 8.2/10, Stage 2 doc 8.2/10). Build notes are in `ORCHESTRATOR-ACCEPTANCE.md` in that folder |

**Parallel sessions.** A row marked *claimed* belongs to the named session. Never work a claimed
row. Parallel sessions each use their own git worktree and push to `main` after rebasing. Only
the lead touches the live checkout, the systemd units, and activation.

## Risks

| Risk | Mitigation |
|---|---|
| Many challengers create false discoveries | Trial register, deflated Sharpe, always-valid tests, factor-neutral IC; no automatic promotion |
| `c-memory` leaks future outcomes | Only labels matured before the decision time; a dedicated leakage test and reviewer |
| Blinding leaks identity through numbers or headlines | Blinding test: a probe asks the blinded model to name the company; record the hit rate |
| The historical corpus is survivor-biased or misdated | Availability = acceptance timestamp for history (the best available), stated; coverage report; research-only authority |
| The time-locked models are too small to be useful | That is itself a result; the look-ahead control still measures contamination |
| The optimizer overfits trailing IC | IC floored at 0, 60-session trailing, fixed λ and κ; compared against the rule-scored twin with the same optimizer |
| Load on the host collides with P15 producers | Separate timers, advisory lock, minute offsets; the text lab runs niced and resumable, outside market hours |
