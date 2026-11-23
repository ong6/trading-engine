# Product

Where the engine is going, what "makes money" means, the product decisions in force and the order
in which admitted work matters. [`AGENTS.md`](../AGENTS.md) governs how sessions work,
[`scope.md`](scope.md) what is admitted, and [`plans/README.md`](plans/README.md) plan status.
[`architecture/system-blueprint.md`](architecture/system-blueprint.md) is the picture of what is
being built and why it might make money. When two admitted items compete, pick the one higher on
this page.

## North star

**An engine that runs on its own and makes money, with AI in the decision loop.** The model
chooses; deterministic code owns data admission, sizing, risk, execution, accounting, halts, and
kill switches. That split is the product, not a temporary safety measure.

"Makes money" has a fixed meaning so no later result can redefine it:

1. **Net of trading and data cost**: commissions, spread and slippage, FX, and data
   subscriptions. Model token cost is excluded from the profitability judgement; tokens are still
   recorded per decision, and model cost is never a reason to stop work or cut corners.
2. **Against the right comparator**: the paired deterministic control for AI policies; SPY or a
   static mix for allocation policies. Positive standalone return is not evidence.
3. **Prospective**: decisions made after the model's training cutoff with frozen prompts, models,
   and rules. Historical LLM backtests are contamination diagnostics only (P10).
4. **Sampled enough**: each policy's pre-registered gate, with a one-sided lower confidence bound
   above zero. For single-name trades this needs hundreds of observations, not twenty: at a
   ~12% per-trade standard deviation, 20 trades can only detect about 5% mean excess per trade.
   The profitability evidence loop (P15) therefore scores every candidate, not just the traded
   ones.
5. **Inside the drawdown envelope**: a policy that can lose most of the book fails regardless of
   its recent run.

## Where it stands

No strategy, public or private, has a proven edge, and everything runs on paper: no broker
connection, no broker credentials, no real capital. What is live (books, registration revision,
producers, forward records, freshness) is reported by `GET /meta` and the generated reports under
[`../data/reports/`](../data/reports/README.md); plan status is in [`plans/README.md`](plans/README.md).

## Stages

| Stage | Goal | Exit | Earliest |
|---|---|---|---|
| 0 · Collect | P15 and engine v2 run the paper books; P7 built but inactive; P8/P9 keep running | P15 scoring, books, and triggers live with coded gates | In progress |
| 1 · Judge | Pre-registered verdicts on each AI policy | Each policy passes or is killed by its own gate | P15 and P8 only at their registered looks; the E1 Monday experiment on 2027-05-10; sector momentum after 2027-10-19 and XS 12-1 after 2031-10-19 (eligibility dates from `/meta`, restarted at D0); P7 at least 12 months after activation |
| 2 · Broker-paper | Same engine on the owner's own hardware against an IBKR paper account | 1–3 months of broker-paper fills reconciled to the simulator, slippage calibrated, zero unattributed orders | After a Stage 1 pass |
| 3 · Small live capital | Autonomous live trading, capped and staged | Live results track paper within tolerance at each capital step | After Stage 2 |
| 4 · Scale | More capital, more policies | Each addition repeats Stages 0–3 | Open |

Stages 2–3 need the open owner decisions below and a separate execution-layer plan. Nothing on
this page authorises a broker connection, credentials, or real capital; `scope.md` governs.

## Decisions in force

Product decisions are the owner's; the reasons and dates are in Git history and the
[archived ledger](history/feedback.md) (background).

**Repository and process**

- This repo is the public infrastructure; new strategies, prompts, registrations, results and
  findings go to the private alpha repo. P15 and P16 as built stay public as a demo.
- The orchestrator owns technical decisions; the owner owns product decisions (`AGENTS.md`).
- Build toward a verdict inside approved plans; lint and complexity findings are not defects.
  There are no per-layer size limits; hygiene budgets are in `scope-budget.json`.
- Commit dates are never rewritten. Docs hold current truth only; dated material lives in
  `docs/history/`.
- Merged `main` with green CI deploys without a live session (P25). The UI is frozen: it keeps
  building and passing its tests, gets no new features and is not designed for mobile.
- Failures are investigated on demand by an agent; there is no push alerting. The driver watchdog
  may recover a stalled scheduled run by itself.

**Data**

- Data stays free: no Sharadar or Norgate purchase and no new API keys (Alpaca, Finnhub, Alpha
  Vantage), because the engine should be able to trade on public data. Survivor-free research
  before 2024-10 stays limited to what free sources allow. Use every free source first, scraping
  included; raw scraped text stays on the host, outside the public repo.
- Free captures: Tiingo listing intervals, SEC Form 25, SEC Companyfacts and Submissions bulk
  archives (acceptance-timestamped), the Massive grouped-daily archive and rolling two-year minute
  history for the frozen small-stock tier (one shared key limiter, isolated storage).
- TradingView is active for research data under owner-held non-display rights and keeps its
  history archive (labelled survivor-biased); it never prices fills or grants execution authority.
  Collection is not paused by a deploy beyond quiescence. Alpaca stays dormant.
- The SEC EDGAR contact is set on the host for P15's `sec_edgar_8k` source; other SEC consumers
  stay inactive until their own plans activate them.
- The `research-text` dependency group (`torch`, `transformers`, separate virtual environment) is
  approved for P16 W4.
- A daily private off-host backup of the store and research files goes to the owner's private data
  repository, restore-checked on every run.

**Engine and accounts (P22)**

- The engine is the executor and ledger; private alpha submits orders and reads results, with one
  independently funded account per alpha version (USD 10,000, 50,000 or 100,000 tiers; new accounts
  start inactive).
- Every simulator book pays the registered commission profile from D0, with a recorded break and a
  restarted evaluation clock.
- Generic paper accounts admit MOO, MOC and deferred-settled intraday fills; legacy books keep their
  registered fill mechanics.
- Margin accounts default to the conservative USD 25k PDT rule; the 2026 intraday-margin rule is an
  explicit account setting. Stock shorting uses explicit short/cover sides, point-in-time locates,
  borrow costs and margin controls.
- An account halts at −20% peak drawdown, −5% daily loss or a ledger/reconciliation mismatch;
  halted positions stay held and marked. The monthly account review is a kill check only; it never
  promotes capital or resumes a halted account.
- A delisted holding is removed: closed out at its last real traded close.
- Options are design-ready and free contract/daily capture is admitted, but execution is refused
  until bid/ask quote data exists.
- Self-learning creates a separately registered version and account only after a passed backtest,
  then measures versions side by side.
- Paper books with no after-cost edge are retired; an agent may retire a no-edge book itself,
  recording the evidence (`active = FALSE`, history and positions kept, one `portfolio_retired`
  audit row).

**Models and policies**

- Engine model calls use GPT-6.1-Sol:max (effort high for once-a-day decisions, medium for events
  and the intraday observers). Every decision keeps the model it was made with; P15 evidence is
  reported pooled and as a post-switch stratum (registration revision 20).
- Paper runs may use the current model under an observable, fail-closed identity; real capital
  needs a provider-issued immutable model revision.
- P7 compares algorithm, AI and hybrid arms on one S$10,000 paper envelope.
- IBKR is the eventual broker (Moomoo fallback); a broker paper account on personal hardware (P17)
  is future work, not now.
- A live paper book may run private research strategies in real time, paper only; they reach this
  engine only through the shared backtest core and paper books.

Standing constraints every decision keeps: simulator-only authority, deterministic account risk
and accounting, no broker code, credentials, or real capital on this host, and no tuning of a
frozen rule after seeing its outcome. New fill types and shorting are generic paper
infrastructure; they grant no private strategy authority by themselves.

### Open product decisions

Each row has the default that applies until the owner decides.

| Decision | Unblocks | Default until decided |
|---|---|---|
| **Private-strategy paper book** | Activation of separately held research in paper books | Generic account intake exists; new accounts stay inactive and strategy activation needs its own admitted gates |
| **Fill model v5 basis**: keep W6 as non-activating continuous-opening measurement, or authorize a separately registered continuous-session cohort before Stage 2 paper-auction evidence exists | Any pre-Stage-2 use of v5 coefficients | Measurement and report only; `baseline_v1` stays the default and direct paper-auction evidence is required for an auction v5 |
| **P8 v1 order authority** once P15 books are live | A single AI book to watch | P8 keeps running as its own cohort |
| **Personal execution host** | Stage 2 | Future work, not now |
| **Model provider for real capital** with a provider-pinned immutable revision | Stage 2+ | Paper only |
| **IBKR account and an execution-layer plan** (tax check first: US dividend withholding and US-situs estate exposure favour UCITS ETFs for allocation sleeves) | Stages 2–3 | Future work; no broker work now |
| **Live loss limits** (proposal: halt at −10% drawdown, −3% daily loss, or any reconciliation mismatch; resume only on owner confirmation) | Stage 3 | None |

## Focus now (in order)

0. **P25 first: ship continuously and clean up** ([plan](plans/p25-ship-autodeploy-cleanup.md)).
   Merged work deploys without waiting on a session; docs and code stay clean; local backup
   history stays short. The UI is frozen: keep it building and tested, add no UI features, and do
   not design for mobile.
1. **Keep the evidence clean and the registered path green.** Use per-stage timings and the hourly
   ops digest to watch collection, snapshots, the queue, observers and status projections. Keep
   scheduled producers green, miss no agent windows, allow no identity drift, and leave no
   uncommitted work on the host. A broken producer beats every item below.
2. **Finish P24 without disturbing the frozen records.** Land the remaining lanes only after both
   timezone suites pass on the merged tree, with one re-pin per batch. Watch the shadow invariant
   monitor.
3. **Finish the P22 engine-v2 cutover**: move the private alpha onto its engine-owned account.
4. **P15 evidence collection.** Keep scheduled windows green and never tune a registered value.
5. **Finish and audit the free survivor-data captures.** Audit the grouped-daily window and let the
   resumable Massive minute service fill its frozen small-stock manifest.
6. **P16 registration, rehearsal, and activation (W9b).** Register and rehearse, then activate only
   the components whose gates permit it: the challenger lab and weekly digest first, the filing
   reader only after its dispatch and activation gates pass. The final refine pass (W10) follows.
7. **P16 synthetic proving ground (W11) as the power test.** Plant a known edge and pure noise and
   record how long each gate takes to detect the edge and how often it passes the noise. Every
   "earliest verdict" date on this page should come from that measurement.
8. **Activate P7.** Backup-gated tri-arm schema and initializer, the recorded SGD/USD opening
   observation, then the tri-arm orchestrator and its status panel.
9. **League collapse (P2).** Retire books that answer no open question to cut nightly noise.
10. **First-fill lifecycle rehearsal.** Rehearse backup and restore across the whole order → fill →
    exit path.

**Build only what the next verdict needs.** The engine already has more built-but-inert
capability than evidence. A new layer, endpoint, or ledger needs a plan and a verdict that asks
for it. How a candidate moves from idea to authority is the
[research funnel](architecture/system-blueprint.md#research-funnel-screen-wide-confirm-narrow).

## Expansion candidates (after Stage 1, each needs its own plan)

| Candidate | Why | Main risk |
|---|---|---|
| AI monthly allocator over broad ETFs | Low turnover, judgement where costs don't eat it (P7's AI-only arm) | May just track a static mix |
| Event-trigger authority | P15 event triggers earn simulator order authority after their own gate | Noise; duplicate decisions |
| Filing and earnings reader on acceptance-timestamped SEC text | Honest point-in-time text input; LLMs read text well | PEAD is thin and crowded |
| Model tournament on identical inputs | Choose the decision-maker on evidence | Trial count |
| Research agent drafting charters for owner approval | Speeds idea → frozen test | Idea flood; cap at one open charter |

Parked: real-time intraday authority (historical-minute fills settle later), new markets, and
options execution (contract capture is admitted, but quote data is absent).

## Stop rules

Stop building toward live capital, and keep the engine as a research and portfolio piece, if by
**2027-09** no AI policy has cleared its gate, if trading and data costs exceed demonstrated
excess return at the capital the owner will deploy, or if work drifts into governance for an edge
that does not exist for two review cycles.
