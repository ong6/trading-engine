# Product

The central product document: where the engine is going, what "makes money" means, every owner
decision (made and open), and the order in which admitted work matters. `AGENTS.md` governs *how*
sessions work, `scope.md` governs *what is admitted*, `feedback.md` keeps the dated verdicts in
full, and [`plans/README.md`](plans/README.md) holds plan status.
[`system-blueprint.md`](system-blueprint.md) is the picture of what is being built and why it
might make money. When two admitted items compete, pick the one higher on this page. Precedence
between documents is defined once, in `AGENTS.md`.

## North star

**An engine that runs on its own and makes money, with AI in the decision loop** (owner,
2026-09-24). The model chooses; deterministic code owns data admission, sizing, risk, execution,
accounting, halts, and kill switches. That split is the product, not a temporary safety measure.

"Makes money" has a fixed meaning so no later result can redefine it:

1. **Net of trading and data cost**: commissions, spread and slippage, FX, and data
   subscriptions. Model token cost is excluded from the profitability judgement (owner,
   2026-09-25). Tokens are still recorded per decision.
2. **Against the right comparator**: the paired deterministic control for AI policies; SPY or a
   static mix for allocation policies. Positive standalone return is not evidence.
3. **Prospective**: decisions made after the model's training cutoff with frozen prompts, models,
   and rules. Historical LLM backtests are contamination diagnostics only in the
   contamination-aware 2022 agent replay (P10).
4. **Sampled enough**: each policy's pre-registered gate, with a one-sided lower confidence bound
   above zero. For single-name trades this needs hundreds of observations, not twenty: at a
   ~12% per-trade standard deviation, 20 trades can only detect about 5% mean excess per trade.
   The profitability evidence loop (P15) therefore scores every candidate, not just the traded
   ones.
5. **Inside the drawdown envelope**: a policy that can lose most of the book fails regardless of
   its recent run.

## What the owner wants now

Built only from [`feedback.md`](feedback.md) entries, newest last, quoting the ledger verbatim. The
end goal is the north star above. The owner's 2026-10-19 and 2026-10-20 directions (infrastructure
and the change process) are not yet recorded in the ledger, so they are not listed here.

- **2026-10-15, engine v2:** "we support the v2, I accept it." (Deployed 2026-10-18.)
- **2026-10-15, delistings:** "A delisted holding is removed: closed out at its last real traded
  close."
- **2026-10-21, senior-quant review (P24):** the owner asked the orchestrator to "act as a senior
  quant: spread many agents out to evaluate and fix the pipelines, improve speed (nightly
  wall-clock, simulator and backtest core, test suite and research evaluators), make alpha
  generation and the engine work properly, and send agents to find new strategies (SEC filings and
  LLM text, microstructure and auction, cross-asset ETF, momentum, and a literature sweep)." "You
  can do anything you want, as long as you feel it needs fixing; no need to ask me anything; you
  can just push."
- **2026-10-22, clear context:** "make sure the docs and everything context wise is clear and we
  know what we are building and the end goal and what we want."

## Where it stands (2026-10-22)

**No policy has yet beaten its frozen control prospectively.** Everything below is paper only: no
broker connection, no broker credentials, no real capital. `GET /meta`, the generated reports
under `data/reports/` and the [plan table](plans/README.md) are the live authority; this section
is a dated summary of them.

**Live now.**

- [Engine v2 (P22)](plans/p22-engine-v2-accounts.md) deployed on 2026-10-18 with D0 on
  2026-10-19: the engine is the sole executor and ledger for paper books and versioned accounts,
  with auction and deferred intraday fills, effective-dated commissions, stock shorts,
  margin/PDT controls, account halts and private/public result isolation. Every book pays the
  registered commission profile from D0, and its evaluation clock restarted there. Options
  execution stays refused without bid/ask quotes.
- The host runs `main` at registration revision 17. Revision 15 (price admission, trusted-bar
  money paths, data-flow, operations and board corrections) was installed on 2026-10-21.
  Revision 16 (P24 batch 1: store-integrity repairs, quant-audit statistics fixes, operations
  evidence fixes, test speed) and revision 17 (P24 batch 2: the SEC acceptance clock, batched
  nightly writes, one summary row for identical intraday re-fetches, the walk-forward dividend
  fix that cut one fold from 4,872 s to 582 s with identical ledgers, audit fixes E5–E8 and P18
  core `p18-study-v3`) followed on `main`. Scoring, labels, statistical gates, schedules and
  frozen valid-data outcomes did not change in any of them.
- The live store repair ran on 2026-10-22: 18,798 rows corrected (split restatements, the WLFC
  bar on a third price basis, never-settled same-night bars). The snapshot invariant monitor runs
  in shadow mode.
- 17 active paper books after the 2026-10-21 retirement of eight books with no after-cost edge,
  including the three [P15](plans/p15-profitability-evidence-loop.md) books (live since
  2026-09-29; collecting, no performance claim before its registered looks). P15's SEC 8-K event
  source works again since revision 17; it had been rejecting almost every response.
- The E1 Monday, sector-momentum and XS 12-1 forward records are `ACCUMULATING`.
- The daily opportunity agent (P8) still assesses nightly standouts; its v1 book was among the
  retired, so it places no simulator orders. The P9 hourly and four-hour observers and the P15
  event triggers stay shadow-only.
- Research-only data runs beside the operational store: the free Massive grouped-daily archive
  (rolling two years from 2024-10) and minute capture for the frozen USD 1–5M tier, the
  TradingView history archive, and the nightly SEC Companyfacts and Submissions bulk archives.
  None of them prices a fill. The 2017 Kaggle archive failed its delisted-name census and was
  not loaded.

**In flight.**

- [P24](plans/p24-quant-review-and-speed.md) (active): the 2026-10-21 senior-quant review. Its
  first two merge batches and the wave-1 lanes (public-hygiene gate, lane tool, release tool in
  dry-run, audit-only job registry, dataset catalogue, research StudySpec runner and cache)
  landed by `483564b6`. The storage revision, now numbered 18, is in review and store-copy
  rehearsal and is **not** live.
- P22's remaining step is the private alpha's move onto its engine-owned account (lane L5,
  held for the post-deploy cutover). The Massive options capture stays paused.
- [P16](plans/p16-challenger-lab-and-text-edge.md)'s evaluation, challenger, filing, replay,
  construction and execution-measurement work (W1–W9a) is built and inert until W9b
  registration, rehearsal and activation. [P7](plans/p7-autonomous-paper-trial.md) is built and
  not activated.
- Since 2026-09-28, new strategy research runs in a private repository against this engine under
  the same census and pre-registration rules; its results are not published here, and no strategy
  there has a proven edge either.

**Built and finished.** The [shared backtest core (P18)](plans/p18-backtest-core.md): on the
registered 3,000-stock × 3,800-session benchmark, 16-worker simulation fell from 989.05 to 0.847
seconds (1,167.5×) with all 295 captured JSON outputs (53,391,323 bytes) byte-identical. The
[offline market-data auditor (P19)](plans/p19-market-data-auditor.md), the
[paper-account boundary (P21)](paper-account-contract.md) and the
[hourly operations digest (P23)](plans/p23-hourly-ops-digest.md) are complete.

## Stages

| Stage | Goal | Exit | Earliest |
|---|---|---|---|
| 0 · Collect | P15 live since 2026-09-29; engine v2 live since 2026-10-18 (D0 2026-10-19); the autonomous paper trial (P7) built but inactive; P8/P9 keep running | P15 scoring, books, and triggers live with coded gates | In progress |
| 1 · Judge | Pre-registered verdicts on each AI policy | Each policy passes or is killed by its own gate | P15 and P8 only at their registered looks; the E1 Monday experiment on 2027-05-10; sector momentum after 2027-10-19 and XS 12-1 after 2031-10-19 (eligibility dates from `/meta`, restarted at D0); P7 at least 12 months after activation |
| 2 · Broker-paper | Same engine on the owner's own hardware against an IBKR paper account | 1–3 months of broker-paper fills reconciled to the simulator, slippage calibrated, zero unattributed orders | After a Stage 1 pass |
| 3 · Small live capital | Autonomous live trading, capped and staged | Live results track paper within tolerance at each capital step | After Stage 2 |
| 4 · Scale | More capital, more policies | Each addition repeats Stages 0–3 | Open |

Stages 2–3 need the open owner decisions below and a separate execution-layer plan. Nothing on
this page authorises a broker connection, credentials, or real capital; `scope.md` still governs.

## Decisions

### Made

Newest first. Full wording and ceiling changes are in [`feedback.md`](feedback.md).

| Date | Decision | Where |
|---|---|---|
| 2026-10-22 | Every agent entry doc opens with one shared block stating what we are building, the end goal (linked to the north star), what is live and what we are working on; other docs link to it instead of restating the goal | feedback; `AGENTS.md`, `README.md`, `docs/README.md` |
| 2026-10-21 | Senior-quant review (P24): spread agents to evaluate and fix the pipelines, improve speed, make alpha generation and the engine work properly, and find new strategies; "You can do anything you want, as long as you feel it needs fixing; no need to ask me anything; you can just push." | P24; feedback |
| 2026-10-21 | Retire paper books with no after-cost edge; agents may retire a no-edge book themselves, recording the evidence. First batch: turtle_breakout, mr_overlay (+gated), daily_opportunity_agent_v1, low_vol, ew_trend_gated, template_top10_banded (+gated); `active = FALSE`, equity history and positions kept, one `portfolio_retired` audit row each | Strategy scorecard 2026-10-20; audit_log |
| 2026-10-15 | A delisted holding is removed: closed out at its last real traded close | P22; feedback |
| 2026-10-15 | Engine v2 (P22) is accepted; the pending revision-14 fixes land in v2 before the Sunday 2026-10-18 deployment (D0 2026-10-19) | P22; feedback |
| 2026-10-06 | The engine is the executor and ledger; private alpha submits orders and reads results, with one independently funded account per alpha version | P22; feedback |
| 2026-10-06 | Every simulator book pays the registered commission profile from parameterized D0, with a recorded break and restarted book-evaluation clock | P22; feedback |
| 2026-10-06 | Generic paper accounts admit MOO, MOC and deferred-settled intraday fills; legacy books retain their registered fill mechanics | P22; feedback |
| 2026-10-06 | Margin accounts default to the conservative legacy USD 25k PDT rule while the 2026 intraday-margin rule remains an explicit account setting | P22; feedback |
| 2026-10-06 | Stock shorting is allowed through explicit short/cover sides, point-in-time locates, borrow costs and margin controls | P22; feedback |
| 2026-10-06 | An account halts at −20% peak drawdown, −5% daily loss or a ledger/reconciliation mismatch; halted positions remain held and marked | P22; feedback |
| 2026-10-06 | Options are design-ready and free contract/daily capture is admitted, but execution is refused until bid/ask quote data exists | P22; feedback |
| 2026-10-06 | Self-learning creates a separately registered version and account only after a passed backtest, then measures versions side by side | P22; feedback |
| 2026-10-06 | The monthly account review is a kill check only; it never promotes capital or automatically resumes a halted account | P22; feedback |
| 2026-10-05 | Fix P20 remaining issues and prove independent strategy accounts with isolated holdings, orders, fills, cash and equity | P21; feedback |
| 2026-10-05 | Review and improve the existing engine and paper dashboard against real host evidence, with independent acceptance and unchanged frozen strategy authority | P20; feedback |
| 2026-10-03 | Start an offline market-data auditor: independent coverage, explicit unknown evidence and a fictional omission demo, with unchanged evaluator/live behavior | P19; feedback |
| 2026-10-02 | Capture the free Massive rolling two-year minute history for the frozen small-stock tier, with one shared key limiter and isolated storage | P3; feedback |
| 2026-10-02 | Use SEC's free nightly Companyfacts and Submissions archives for isolated point-in-time fundamentals and acceptance-timestamped earnings events | P3; feedback |
| 2026-10-02 | The free Massive key is available and the isolated two-year grouped-daily capture is running resumably; paid point-in-time data remains deferred | P3; site data |
| 2026-10-02 | Failures are investigated on demand by an agent. There is no push alerting | This page; site operations |
| 2026-10-02 | A broker paper account on personal hardware, described by the personal-host broker paper plan (P17), is future work and explicitly not work for now | P17; this page; site roadmap |
| 2026-10-02 | A live paper book will run private research strategies in real time, paper only. Private research strategies stay in a separate private repository and reach this engine only through the shared backtest core and paper books | This page; site roadmap |
| 2026-10-01 | SEC EDGAR contact set on the host (private environment file, scoped to the P15 event service), enabling P15's registered `sec_edgar_8k` source; other SEC consumers stay inactive until their own plans activate them | P15, this page |
| 2026-10-01 | No data purchase for now: point-in-time data (P3) proceeds with a free-source phase 0 (Tiingo listing intervals, Massive free daily bars once the key exists, SEC Form 25) | P3, feedback |
| 2026-10-01 | The shared backtest core (P18) approved | P18, feedback |
| 2026-09-29 | Daily private off-host backup of the store and research files, restore-checked on every run | feedback, `scope.md` |
| 2026-09-28 | This repo is the public infrastructure; new strategies, prompts, registrations, results and findings go to a private alpha repo. P15 and P16 as built stay public as a demo | AGENTS, feedback |
| 2026-09-27 | Add a synthetic end-to-end proving ground with evaluation loops (P16 W11) once the main issues are fixed | P16 |
| 2026-09-27 | Technical decisions in orchestrated runs belong to the orchestrating agent; the owner keeps product decisions. Per-layer size limits removed | `AGENTS.md`, feedback |
| 2026-09-26 | Replace maintain-only framing with build-toward-verdict guidance; add the system blueprint; keep P16 proposed until P15 W8 | AGENTS, blueprint, P16, feedback |
| 2026-09-26 | P16 approved with ceilings. P15 activation is held and moves into P16 W0 after the review fixes (R1–R16). The `improve-work` refine loop gates each registration and ends the run | P16, feedback |
| 2026-09-26 | Data: use every free source first, scraping included; paid data waits (owner). Raw scraped text stays on the host, outside the public repo | P16 |
| 2026-09-26 | Instructions refreshed: build toward a verdict inside plans; lint is not a defect; appliance mode (P1) closed | feedback |
| 2026-09-25 | P15 approved: score every candidate, add deterministic comparator books, add a pre-open check and event-driven shadow triggers, and code the gates. It may run as one long session with sub-agents | [P15](plans/p15-profitability-evidence-loop.md), feedback |
| 2026-09-25 | Model token cost is excluded from the profitability definition; trading and data costs still count | This page |
| 2026-09-25 | This page is the central product and decision document (was `direction.md`) | This page |
| 2026-09-25 | TradingView active for research data under owner-held non-display rights; never prices fills or grants execution authority. Alpaca stays dormant | Market-data source hardening (P13), TradingView historical archive (P14) |
| 2026-09-25 | Build a resumable TradingView daily-history archive, labelled survivor-biased | P14 |
| 2026-09-24 | End goal: runs on its own and makes money with AI in the loop | This page |
| 2026-09-24 | Docs hygiene: dated snapshots in `docs/history/`, one plan-status table, no hash chains in prose, no host identifiers | feedback |
| 2026-09-23 | Evaluation ledger (P11) and the agent research product (P12) | P11, P12 |
| 2026-09-22 | Daily opportunity agent (P8); multi-cadence agents and locked simulator trade tool (P9); contamination-labelled 2022 replay (P10) | P8, P9, P10 |
| 2026-09-20 | S$10,000 paper envelope; three-arm algorithm / AI / hybrid comparison (P7) | P7 |
| 2026-09-20 | Paper runs may use the current model under an observable, fail-closed identity; real capital needs a provider-issued immutable model revision | feedback |
| 2026-09-20 | IBKR is the eventual broker (Moomoo fallback); Sharadar is the preferred point-in-time data vendor (Norgate fallback) | Broker decision (P4), P3 |
| 2026-09-19 | P1–P4 approved; verified commits may be pushed | feedback |
| 2026-09-18 | Maintain mode with an admission test and LOC ceilings; build only inside approved plans | `AGENTS.md`, feedback |
| 2026-09-18 | Repo public; commit dates are never rewritten | feedback |

Standing constraints that every decision above keeps: simulator-only authority, deterministic
account risk and accounting, no broker code, credentials, or real capital on this host, and no
tuning of a frozen rule after seeing its outcome. New fill types and shorting are generic P22
paper infrastructure; they grant no private strategy authority by themselves.

### Open (owner only)

Each row has the default that applies until the owner decides.

| Decision | Unblocks | Default until decided |
|---|---|---|
| **Failure response** | Operational follow-up | Decided 2026-10-02: an agent investigates on demand; no push alerting |
| **Private-strategy paper book** | Activation of separately held research in paper books | P21 generic account intake is implemented; new accounts remain inactive and strategy activation still needs its own admitted gates |
| **Fill model v5 basis**: keep W6 as non-activating continuous-opening measurement, or authorize a separately registered continuous-session cohort before Stage 2 paper-auction evidence exists | Any pre-Stage-2 use of v5 coefficients | Measurement and report only; `baseline_v1` remains the default and direct paper-auction evidence is required for an auction v5 |
| **`research-text` dependency group** (`torch`, `transformers` in a separate virtual environment) | P16's time-locked historical text lab | P16 W4 stops after building the corpus |
| **P8 v1 order authority** once P15 books are live | A single AI book to watch | P8 v1 keeps running unchanged as its own cohort |
| **P3 data budget**: initial and recurring ceiling for Sharadar (or Norgate) | Survivor-free point-in-time universe and fundamentals before 2024-10; historical stock-selection research | No purchase (decided 2026-10-01); free-source phase 0 only |
| **Commit metadata rewrite** for 2026-09-18 to 09-23 author and trailer lines that break the public-hygiene rule | Clean public history | Not rewritten (needs a force-push; dates would be kept). 2026-10-20: done; the public history was rewritten for author and trailer identity only, with commit dates and trees kept and the old-to-new commit map held privately ([history index](history/README.md)) |
| **Free API keys** (Alpaca, including the Benzinga news archive; Finnhub; Alpha Vantage) | Extra historical news for the P16 replay lab; a second realtime cross-check | Free bulk archives and scraping only (GDELT, CC-NEWS, EDGAR, wire and IR pages, Wayback) |
| **Personal execution host** | Stage 2 | Future work, explicitly not now (decided 2026-10-02) |
| **Model provider for real capital** with a provider-pinned immutable revision | Stage 2+ | Paper only |
| **IBKR account and an execution-layer plan** (tax check first: US dividend withholding and US-situs estate exposure favour UCITS ETFs for allocation sleeves) | Stages 2–3 | Future work; no broker work now (decided 2026-10-02) |
| **Live loss limits** (proposal: halt at −10% drawdown, −3% daily loss, or any reconciliation mismatch; resume only on owner confirmation) | Stage 3 | None |

## Focus now (in order)

Updated 2026-10-22 for engine v2 live and P24 active.

1. **Keep the evidence clean and the revision 17 registered path green.** Use per-stage timings
   and the hourly ops digest to watch collection, snapshots, the queue, observers and status
   projections. Keep scheduled producers green, miss no agent windows, allow no identity drift,
   and leave no uncommitted work on the host. A broken producer beats every item below.
2. **Finish P24 without disturbing the frozen records.** Land the remaining lanes only after both
   timezone suites pass on the merged tree, with one re-pin per batch. The storage revision
   (revision 18) goes live only after its review findings are fixed and its store-copy rehearsal
   passes. Watch the invariant monitor (shadow) after the 2026-10-22 store repair.
3. **Finish the P22 engine-v2 cutover.** Engine v2 deployed 2026-10-18 (D0 2026-10-19); the
   commit-identity rewrite of the older public history was done on 2026-10-20. Still to do: the
   private alpha's move onto its engine-owned account. The Massive options capture stays paused
   after its first run failed on provider responses.
4. **P15 evidence collection.** P15 is active after its scoring, pre-open, event, report, and
   status checks passed; its SEC 8-K source works again since revision 17. Keep scheduled windows
   green and never tune a registered value.
5. **Finish and audit the free survivor-data captures.** Audit the completed grouped-daily window
   and let the resumable Massive minute service fill its frozen small-stock manifest. Paid
   pre-2024-10 data remains blocked on a future spend decision.
6. **P16 registration, rehearsal, and activation (W9b).** Register and rehearse, then activate
   only the components whose gates permit it: the challenger lab and weekly digest first, the
   filing reader only after its remaining dispatch and activation gates pass. The final refine
   pass (W10) follows.
7. **P16 synthetic proving ground (W11) as the power test.** Plant a known edge and pure noise in the synthetic proving
   ground, and record how long each gate takes to detect the edge and how often it passes the
   noise. Every "earliest verdict" date on this page should come from that measurement.
8. **Activate P7.** Backup-gated tri-arm schema and initializer, the recorded SGD/USD opening
   observation, then the tri-arm orchestrator and its status panel. It tests whether the AI
   allocates better than the rule at low turnover, which the research verdicts favour.
9. **League collapse (P2).** Retire books that answer no open question to cut nightly noise. The
   first batch of eight no-edge books was retired on 2026-10-21 (17 books remain active).
10. **First-fill lifecycle rehearsal.** Rehearse backup and restore across the whole order → fill →
    exit path using the P8 FSLY position.

**Build only what the next verdict needs.** The engine already has more built-but-inert
capability than evidence. A new layer, endpoint, or ledger needs a plan and a verdict that asks
for it (the 2026-09-18 failure mode). How a candidate moves from idea to authority is the
[research funnel](system-blueprint.md#research-funnel-screen-wide-confirm-narrow).

## Expansion candidates (after Stage 1, each needs its own plan)

| Candidate | Why | Main risk |
|---|---|---|
| AI monthly allocator over broad ETFs | Low turnover, judgement where costs don't eat it (P7's AI-only arm) | May just track a static mix |
| Event-trigger authority | P15 event triggers earn simulator order authority after their own gate | Noise; duplicate decisions |
| Filing and earnings reader on acceptance-timestamped SEC text | Honest point-in-time text input; LLMs read text well | PEAD is thin and crowded |
| Model tournament on identical inputs | Choose the decision-maker on evidence | Trial count |
| Research agent drafting charters for owner approval | Speeds idea → frozen test | Idea flood; cap at one open charter |

Parked: real-time intraday authority (P22's historical-minute fills settle later), new markets,
and options execution (contract capture is admitted, but quote data is absent).

## Stop rules

Stop building toward live capital, and keep the engine as a research and portfolio piece, if by
**2027-09** no AI policy has cleared its gate, if trading and data costs exceed demonstrated
excess return at the capital the owner will deploy, or if work drifts back into governance for an
edge that does not exist for two review cycles (the 2026-09-18 failure mode).

<!-- sources: BUILDLOG.md, docs/plans/README.md, docs/plans/p3-point-in-time-data.md, docs/plans/p15-profitability-evidence-loop.md, docs/plans/p16-challenger-lab-and-text-edge.md, docs/plans/p17-personal-host-ibkr-paper-execution.md, docs/plans/p18-backtest-core.md, engine/free_sources.py, server/p15-registration.json, server/p16-registration.json, tools/free_sources.py -->
