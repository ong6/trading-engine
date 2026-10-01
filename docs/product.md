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
   and rules. Historical LLM backtests are contamination diagnostics only (P10).
4. **Sampled enough**: each policy's pre-registered gate, with a one-sided lower confidence bound
   above zero. For single-name trades this needs hundreds of observations, not twenty: at a
   ~12% per-trade standard deviation, 20 trades can only detect about 5% mean excess per trade.
   P15 therefore scores every candidate, not just the traded ones.
5. **Inside the drawdown envelope**: a policy that can lose most of the book fails regardless of
   its recent run.

## Where it stands (2026-09-30)

The appliance is mature: nightly data, screen, league, three frozen forward records, weekly
walk-forward, recovery bundles, TradingView research data, and a live nightly AI agent with a
locked simulator trade tool (P8/P9) whose decisions land in one evaluation ledger (P11/P12).
**No policy has yet beaten its frozen control prospectively.**

[P15](plans/p15-profitability-evidence-loop.md) went live on 2026-09-29 after a verified 90-table
recovery bundle. Registration revision 4, issued only for the label validator, is active. Its
first scoring cycle completed 60 candidates and 18 samples, the report refreshed, and the
pre-open and event cycles remained green, so P15 is `active` and collecting. The earliest first
look is 2026-12-31. No P15 performance claim exists before its registered looks.

[P16](plans/p16-challenger-lab-and-text-edge.md) W1–W8 and W9a are built and remain inert:
evaluation v2, the challenger and filing paths, historical text/replay labs, deterministic
portfolio construction, opening-fill measurement, the weekly digest, and the Stage 2 design. The
public P5–P16 census holds 103 registrations with conservative weighted trial contribution
N=139. W9b owns registration, rehearsals, and any activation.

Since 2026-09-28, new strategy research runs in a private repository against this engine under
the same census and pre-registration rules; its results are not published here.

## Stages

| Stage | Goal | Exit | Earliest |
|---|---|---|---|
| 0 · Collect | P15 live (since 2026-09-29); P7 activated; P8/P9 keep running | P15 scoring, books, and triggers live with coded gates | ~2026-11 |
| 1 · Judge | Pre-registered verdicts on each AI policy | Each policy passes or is killed by its own gate | P15 scoring first look 2026-12-31; P8 ~2027-02; E1 2027-05-10; sector momentum 2027-09-04; P7 ≥12 months after activation |
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
| 2026-10-01 | SEC EDGAR contact set on the host (private environment file, scoped to the P15 event service), enabling P15's registered `sec_edgar_8k` source; other SEC consumers stay inactive until their own plans activate them | P15, this page |
| 2026-10-01 | No data purchase for now: P3 proceeds with a free-source phase 0 (Tiingo listing intervals, Massive free daily bars once the key exists, SEC Form 25) | P3, feedback |
| 2026-10-01 | P18 shared backtest core approved | P18, feedback |
| 2026-09-29 | Daily private off-host backup of the store and research files, restore-checked on every run | feedback, `scope.md` |
| 2026-09-28 | This repo is the public infrastructure; new strategies, prompts, registrations, results and findings go to a private alpha repo. P15 and P16 as built stay public as a demo | AGENTS, feedback |
| 2026-09-27 | Add a synthetic end-to-end proving ground with evaluation loops (P16 W11) once the main issues are fixed | P16 |
| 2026-09-27 | Technical decisions in orchestrated runs belong to the orchestrating agent (Claude Opus); the owner keeps product decisions. Per-layer size limits removed | `AGENTS.md`, feedback |
| 2026-09-26 | Replace maintain-only framing with build-toward-verdict guidance; add the system blueprint; keep P16 proposed until P15 W8 | AGENTS, blueprint, P16, feedback |
| 2026-09-26 | P16 approved with ceilings. P15 activation is held and moves into P16 W0 after the review fixes (R1–R16). The `improve-work` refine loop gates each registration and ends the run | P16, feedback |
| 2026-09-26 | Data: use every free source first, scraping included; paid data waits (owner). Raw scraped text stays on the host, outside the public repo | P16 |
| 2026-09-26 | Instructions refreshed: build toward a verdict inside plans; lint is not a defect; P1 closed | feedback |
| 2026-09-25 | P15 approved: score every candidate, add deterministic comparator books, add a pre-open check and event-driven shadow triggers, and code the gates. It may run as one long session with sub-agents | [P15](plans/p15-profitability-evidence-loop.md), feedback |
| 2026-09-25 | Model token cost is excluded from the profitability definition; trading and data costs still count | This page |
| 2026-09-25 | This page is the central product and decision document (was `direction.md`) | This page |
| 2026-09-25 | TradingView active for research data under owner-held non-display rights; never prices fills or grants execution authority. Alpaca stays dormant | P13, P14 |
| 2026-09-25 | Build a resumable TradingView daily-history archive, labelled survivor-biased | P14 |
| 2026-09-24 | End goal: runs on its own and makes money with AI in the loop | This page |
| 2026-09-24 | Docs hygiene: dated snapshots in `docs/history/`, one plan-status table, no hash chains in prose, no host identifiers | feedback |
| 2026-09-23 | Evaluation ledger (P11) and the agent research product (P12) | P11, P12 |
| 2026-09-22 | Daily opportunity agent (P8); multi-cadence agents and locked simulator trade tool (P9); contamination-labelled 2022 replay (P10) | P8, P9, P10 |
| 2026-09-20 | S$10,000 paper envelope; three-arm algorithm / AI / hybrid comparison (P7) | P7 |
| 2026-09-20 | Paper runs may use the current model under an observable, fail-closed identity; real capital needs a provider-issued immutable model revision | feedback |
| 2026-09-20 | IBKR is the eventual broker (Moomoo fallback); Sharadar is the preferred point-in-time data vendor (Norgate fallback) | P4, P3 |
| 2026-09-19 | P1–P4 approved; verified commits may be pushed | feedback |
| 2026-09-18 | Maintain mode with an admission test and LOC ceilings; build only inside approved plans | `AGENTS.md`, feedback |
| 2026-09-18 | Repo public; commit dates are never rewritten | feedback |

Standing constraints that every decision above keeps: simulator-only authority, long-only,
next-open fills, no broker code, credentials, or real capital on this host, and no tuning of a
frozen rule after seeing its outcome.

### Open (owner only)

Each row has the default that applies until the owner decides.

| Decision | Unblocks | Default until decided |
|---|---|---|
| **Fill model v5 basis**: keep W6 as non-activating continuous-opening measurement, or authorize a separately registered continuous-session cohort before Stage 2 paper-auction evidence exists | Any pre-Stage-2 use of v5 coefficients | Measurement and report only; `baseline_v1` remains the default and direct paper-auction evidence is required for an auction v5 |
| **`research-text` dependency group** (`torch`, `transformers` in a separate virtual environment) | P16's time-locked historical text lab | P16 W4 stops after building the corpus |
| **Simulator short side** | Using the ~half of candidates that are losers | Long-only. P15 filters candidates to upside and trend names |
| **P8 v1 order authority** once P15 books are live | A single AI book to watch | P8 v1 keeps running unchanged as its own cohort |
| **P3 data budget**: initial and recurring ceiling for Sharadar (or Norgate) | Survivor-free point-in-time universe and fundamentals before 2024-10; historical stock-selection research | No purchase (decided 2026-10-01); free-source phase 0 only |
| **Massive free key** (individual-use Stocks Basic) | Two years of survivor-free daily bars for every US stock (P3 phase 0 fetcher is built) | Fetcher stays unrun |
| **Commit metadata rewrite** for 2026-09-18 to 09-23 author and trailer lines that break the public-hygiene rule | Clean public history | Not rewritten (needs a force-push; dates would be kept) |
| **Free API keys** (Alpaca, including the Benzinga news archive; Finnhub; Alpha Vantage) | Extra historical news for the P16 replay lab; a second realtime cross-check | Free bulk archives and scraping only (GDELT, CC-NEWS, EDGAR, wire and IR pages, Wayback) |
| **Personal execution host** | Stage 2 | None |
| **Model provider for real capital** with a provider-pinned immutable revision | Stage 2+ | Paper only |
| **IBKR account and an execution-layer plan** (tax check first: US dividend withholding and US-situs estate exposure favour UCITS ETFs for allocation sleeves) | Stages 2–3 | No broker work |
| **Live loss limits** (proposal: halt at −10% drawdown, −3% daily loss, or any reconciliation mismatch; resume only on owner confirmation) | Stage 3 | None |

## Focus now (in order)

1. **Keep the evidence clean.** Scheduled producers green, no missed agent windows, no identity
   drift, no uncommitted work on the host (the nightly `git pull` fails on a dirty tree).
   A broken producer beats every item below.
2. **P15 evidence collection.** P15 is active after its first scoring, pre-open, event, report,
   and status checks passed. Keep the remaining first-cycle windows through 2026-10-01 green;
   never tune a registered value.
3. **[P16](plans/p16-challenger-lab-and-text-edge.md) W9b.** Register and rehearse, then activate
   only the components whose gates permit it: the challenger lab and weekly digest first, the
   filing reader once the SEC contact is set. W10's refine pass follows.
4. **P16 W11 as the power test.** Plant a known edge and pure noise in the synthetic proving
   ground, and record how long each gate takes to detect the edge and how often it passes the
   noise. Every "earliest verdict" date on this page should come from that measurement.
5. **Activate P7.** Backup-gated tri-arm schema and initializer, the recorded SGD/USD opening
   observation, then the tri-arm orchestrator and its status panel. It tests whether the AI
   allocates better than the rule at low turnover, which the research verdicts favour.
6. **P2 league collapse.** Retire books that answer no open question to cut nightly noise.
7. **First-fill lifecycle rehearsal.** Rehearse backup and restore across the whole order → fill →
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

Parked: intraday execution authority (needs quote/trade data and queue modelling), new markets,
options (premium selling showed no after-cost edge), shorting (open decision above).

## Stop rules

Stop building toward live capital, and keep the engine as a research and portfolio piece, if by
**2027-09** no AI policy has cleared its gate, if trading and data costs exceed demonstrated
excess return at the capital the owner will deploy, or if work drifts back into governance for an
edge that does not exist for two review cycles (the 2026-09-18 failure mode).
