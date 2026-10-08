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

## Where it stands (2026-10-06)

The engine runs nightly data collection, screening, a paper league, three frozen forward records,
weekly walk-forward checks, recovery bundles, research-only market data, and the daily opportunity
agent (P8) with its locked simulator trade tool. The multi-cadence agent tools (P9) add shadow
observers. Their decisions land in the forward agent evaluation ledger (P11) and agent research
product (P12).
**No policy has yet beaten its frozen control prospectively.**

[The profitability evidence loop (P15)](plans/p15-profitability-evidence-loop.md) went live on
2026-09-29 after a verified 90-table recovery bundle. The current source registration is
revision 13: exact validation of cash-resized SPY reinvestment fills and nightly maturation of
existing event-shadow labels before reporting, retaining revision 12's bounded complete-metadata
recovery and earlier verifier, identity, provider-refusal and backup corrections.
Scoring, book mechanics, gates, label values, registered values, schedules and written evidence
are unchanged.
P15 is `active` and collecting; no performance claim exists before its registered looks.
Earlier operational revisions introduced stage timings, bounded collection, snapshot throttling,
cached status projections and queue scratch handling. Revision 10 corrected pending
nightly-marked book validation; that correction remains in force.

[The shared backtest core (P18)](plans/p18-backtest-core.md) is done. It builds one immutable
columnar price panel and shares it with forked workers. On the registered 3,000-stock × 3,800-session
benchmark, 16-worker simulation fell from 989.05 to 0.847 seconds (1,167.5×), while all 295 captured
pre-existing JSON outputs (53,391,323 bytes) stayed byte-identical. Event studies must now declare
both their window-end treatment and whether they require a complete held-price path.

The free Massive key is present in a private owner-only file. The isolated grouped-daily archive
holds 501 sessions from 2024-10-02 through 2026-10-01, and its daily service keeps the rolling
window current. Its initial proof date loaded 12,613 US securities. This improves survivor coverage
but does not provide pre-2024-10 bars or mutate operational prices.

The free Massive minute capture is also prepared and running independently. Its frozen host-only
manifest has 3,302 tickers: SPY, QQQ, IWM, and every Tiingo-admitted USD Stock that entered the
USD 1--5M point-in-time MDV60 tier in the completed grouped-daily archive. Ten 50-session chunks
per ticker produce a 33,020-request estimate; the capture is resumable, window-aware, and isolated
from operational and execution prices.

The free 2017 Kaggle price archive was also censused before any loader was built. Only 1 of 247
sampled Tiingo-ended intervals matched both endpoints within ±5 sessions (0.405%, below the frozen
30% gate), and just 10 of 8,507 populated archive tickers ended more than 30 sessions before the
archive boundary. It is a current-at-cutoff, current-vintage-adjusted survivor snapshot; the
recommendation is skip and zero rows were loaded.

P3's free SEC phase now also admits the nightly Companyfacts and Submissions bulk archives for
point-in-time core fundamentals and acceptance-timestamped item 2.02 earnings events. The completed
isolated audit contains 12,170,777 facts for 17,096 companies and 421,723 events, with 93.8%
combined ticker matching. Raw archives remain host-only; no operational or execution table changed.

[The challenger lab, text edge, and evaluation science plan
(P16)](plans/p16-challenger-lab-and-text-edge.md) has built its evaluation through broker-paper
design workstreams (W1–W8) and the cleanup half of activation (W9a). They remain inert. The
registration, rehearsal, and activation half (W9b) still owns any activation.

Since 2026-09-28, new strategy research runs in a private repository against this engine under
the same census and pre-registration rules; its results are not published here.

P21 implements the generic [paper-account boundary](paper-account-contract.md). Private alpha
owns generation, trade specifications and manual/all/auto planning across USD 10k/50k/100k
tiers; the engine owns each account's funding, holdings, orders, fills, cash and equity. New
accounts start inactive. Selecting or testing a tier grants no strategy activation. Stock/ETF
requests use the existing next-open simulator; options and futures are refused until their
execution models and authority are separately admitted.

[Engine v2 accounts and money (P22)](plans/p22-engine-v2-accounts.md) is active. It makes the
public engine the sole executor and ledger for versioned private-alpha accounts, adds auction and
deferred intraday paper fills, effective-dated commissions, stock shorts, margin/PDT controls,
account halts and private/public result isolation. Existing books change only at an explicit D0
cost break with restarted evaluation clocks. Account settings live beside the frozen positional
`portfolios` table in `portfolio_accounts`; options execution remains refused without quotes.

## Stages

| Stage | Goal | Exit | Earliest |
|---|---|---|---|
| 0 · Collect | P15 live since 2026-09-29; the autonomous paper trial (P7) built but inactive; P8/P9 keep running | P15 scoring, books, and triggers live with coded gates | In progress |
| 1 · Judge | Pre-registered verdicts on each AI policy | Each policy passes or is killed by its own gate | P15 and P8 only at their registered looks; the E1 Monday experiment on 2027-05-10; sector momentum on 2027-09-04; P7 at least 12 months after activation |
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
| **Commit metadata rewrite** for 2026-09-18 to 09-23 author and trailer lines that break the public-hygiene rule | Clean public history | Not rewritten (needs a force-push; dates would be kept) |
| **Free API keys** (Alpaca, including the Benzinga news archive; Finnhub; Alpha Vantage) | Extra historical news for the P16 replay lab; a second realtime cross-check | Free bulk archives and scraping only (GDELT, CC-NEWS, EDGAR, wire and IR pages, Wayback) |
| **Personal execution host** | Stage 2 | Future work, explicitly not now (decided 2026-10-02) |
| **Model provider for real capital** with a provider-pinned immutable revision | Stage 2+ | Paper only |
| **IBKR account and an execution-layer plan** (tax check first: US dividend withholding and US-situs estate exposure favour UCITS ETFs for allocation sleeves) | Stages 2–3 | Future work; no broker work now (decided 2026-10-02) |
| **Live loss limits** (proposal: halt at −10% drawdown, −3% daily loss, or any reconciliation mismatch; resume only on owner confirmation) | Stage 3 | None |

## Focus now (in order)

1. **Keep the evidence clean and the revision 13 operating path green.** Use per-stage timings to
   watch the bounded collection, shared snapshots, queue, observers, and status projections. Keep
   scheduled producers green, miss no agent windows, allow no identity drift, and leave no
   uncommitted work on the host. A broken producer beats every item below.
2. **Finish P22 engine-v2 integration without disturbing pre-D0 evidence.** Merge the account,
   execution and data lanes, rehearse the parameterized cost migration on a store copy, then
   issue the explicit frozen-contract revisions and P15 revision 13 before Sunday deployment.
3. **P15 evidence collection.** P15 is active after its scoring, pre-open, event, report, and
   status checks passed. Keep scheduled windows green and never tune a registered value.
4. **Finish and audit the free survivor-data captures.** Audit the completed grouped-daily window
   and let the resumable Massive minute service fill its frozen small-stock manifest. Paid
   pre-2024-10 data remains blocked on a future spend decision.
5. **P16 registration, rehearsal, and activation (W9b).** Register and rehearse, then activate
   only the components whose gates permit it: the challenger lab and weekly digest first, the
   filing reader only after its remaining dispatch and activation gates pass. The final refine
   pass (W10) follows.
6. **P16 synthetic proving ground (W11) as the power test.** Plant a known edge and pure noise in the synthetic proving
   ground, and record how long each gate takes to detect the edge and how often it passes the
   noise. Every "earliest verdict" date on this page should come from that measurement.
7. **Activate P7.** Backup-gated tri-arm schema and initializer, the recorded SGD/USD opening
   observation, then the tri-arm orchestrator and its status panel. It tests whether the AI
   allocates better than the rule at low turnover, which the research verdicts favour.
8. **League collapse (P2).** Retire books that answer no open question to cut nightly noise.
9. **First-fill lifecycle rehearsal.** Rehearse backup and restore across the whole order → fill →
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
