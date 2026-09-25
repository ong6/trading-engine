---
plan: P16
title: Challenger lab, text edge, and evaluation science
status: proposed
opened: 2026-09-26
owner_decision: approve once P15 W8 (activation) is done; confirm ceilings and the optional research-text dependency group
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
4. **Historical text lab.** A contamination-controlled historical test of the text signal, using
   time-locked language models whose training data ends before each test year.
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

- **P15 W8 done:** P15 books, scoring, labels v2, and the `p15` status section are live. P16 reads
  them and never edits P15's registered code paths.
- **Owner:**
  - approves this plan and its ceilings (a `feedback.md` entry);
  - optionally sets `TRADING_ENGINE_SEC_USER_AGENT` (without it, W3 builds and tests against
    fixtures and reports `unconfigured`);
  - optionally approves the `research-text` dependency group for W4.
- **Where it runs:** the host, as in P15's "Where this runs".

## Frozen registration (fill in, commit, then never edit)

As in P15: write `server/p16-registration.json` with every value below and the code identities,
and commit it by itself before any P16 evidence is produced. Changes after activation are new
versions. Values marked *(builder sets)* are chosen once from engineering constraints and recorded.

**Evaluation science (`p16-eval-v1`, reporting; never changes P15's gates):**
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

- **W0: Baseline.**
  - Confirm P15 is active and healthy.
  - Take a recovery bundle.
  - Run a **prompt review** of every live model prompt, and write findings into
    `docs/design/prompt-review.md`. These feed `prompt-v2`; live prompts are not edited.
  - Record the P15 pre-activation dispersion that the mSPRT mixing variance needs.
- **W1: Evaluation science v2** in `farm/`: factor-neutral IC, mSPRT, trial register and deflated
  Sharpe, transfer coefficient. Tests use synthetic series with known answers (for example, a
  score equal to momentum must show ≈ 0 factor-neutral IC).
- **W2: Challenger lab.** A generic challenger runner that shares the P15 bundle, the registration,
  and the eight challengers. It runs from its own timer after the P15 nightly scoring, with the
  advisory lock. Include a dry-run.
- **W3: Filing reader**, with a fixture-based suite and live activation only if the SEC contact is
  set.
- **W4: Historical text lab.** The corpus builder (resumable, checkpointed like P14), the
  time-locked scoring, and the report `data/reports/research/textlab.md`.
- **W5: Portfolio construction v2**: the optimizer, the two shadow books, and a dry-run.
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
  - Retire the doc-pinning tests (`tests/test_docs*.py`), carried over from the closed P1, and
    split `docs/how-it-works.md` into an ops runbook and an architecture reference.
  - Delete P16-obsoleted code before activation.
  - Update `system-blueprint.md` (layers table), `product.md`, `how-it-works.md`, and `scope.md`.
  - Commit the registration by itself, activate on a date at least one dry-run day away, and
    verify the first live cycle of each new producer.

## Not in scope

- Order authority for any challenger, filing decision, or construction book beyond its isolated
  shadow simulator book. No change to P15, P8, P7, or frozen records.
- Broker code, connections, credentials, real capital, shorting, leverage, options.
- Fine-tuning any model on the engine's labels.
- Changing a live prompt in place. A prompt change is a new version.
- Using the historical text lab or any pre-cutoff result to promote a policy.
- New endpoints beyond extending `GET /agent/evaluation/status` with `p16` and the digest file.

## Done when

- The full suite passes, both under the host's timezone and with `TZ=UTC`, and
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
- The first weekly digest exists.
- `docs/design/stage2-broker-paper.md` exists, and the draft execution plan is `proposed`.
- Independent reviews of W1–W9 have no open findings.

## Budget

- **Proposed ceilings** (the owner confirms in `feedback.md` on approval; caps, not targets):
  - server +2,000
  - engine +1,500
  - farm +1,800
  - tools +400
  - sim +300
- W4's `research-text` code lives under `farm/textlab/` and counts toward farm.
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
- **Ask for decisions early.** Write a one-line entry under "Owner inputs needed" in the progress
  table the moment a decision blocks progress, and continue with the next unblocked workstream.

## Progress

| Workstream | Status | Evidence (BUILDLOG date) |
|---|---|---|
| W0 Baseline and prompt review | not started | |
| W1 Evaluation science v2 | not started | |
| W2 Challenger lab | not started | |
| W3 Filing reader | not started | |
| W4 Historical text lab | not started | |
| W5 Portfolio construction v2 | not started | |
| W6 Execution realism | not started | |
| W7 Operator digest | not started | |
| W8 Stage 2 design | not started | |
| W9 Cleanup, docs, activation | not started | |

Owner inputs needed: none yet.

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
