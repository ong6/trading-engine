# Direction

The one page that says where this engine is going and what to work on next. `AGENTS.md` governs
*how* sessions work; `scope.md` governs *what is admitted*; this page orders the admitted work by
how much it moves the project toward its goal. When two admitted items compete, pick the one
higher on this page.

## North star

**An engine that runs on its own and makes money, with AI in the decision loop** (owner,
2026-09-24). The model chooses; deterministic code owns data admission, sizing, risk, execution,
accounting, halts, and kill switches. That split is the product, not a temporary safety measure.

"Makes money" has a fixed meaning so no later result can redefine it:

1. **Net of every cost** — commissions, spread and slippage, FX, model tokens, and data
   subscriptions.
2. **Against the right comparator** — the paired deterministic control for AI overlays; SPY or a
   static mix for allocation policies. Positive standalone return is not evidence.
3. **Prospective** — decisions made after the model's training cutoff with frozen prompts, models,
   and rules. Historical LLM backtests are contamination diagnostics only (P10).
4. **Sampled enough** — the plan's own gate (e.g. ≥60 sessions, 90 days and ≥20 completed trades
   for P8; ≥12 paired monthly decisions for P7) with a lower confidence bound above zero.
5. **Inside the drawdown envelope** — a policy that can lose most of the book fails regardless of
   its recent run.

## Where it stands

The appliance is mature: nightly data, screen, league, three frozen forward records, weekly
walk-forward, recovery bundles, and a live nightly AI agent with a locked simulator trade tool
(P8/P9) whose decisions land in one evaluation ledger (P11/P12). **No policy has yet beaten its
frozen control prospectively.** The binding constraint is evidence time, not code.

## Stages

| Stage | Goal | Exit | Earliest |
|---|---|---|---|
| 0 · Collect | P8/P9 run untouched; P7 activated | P7 three arms live; P8 at its sample gate | ~2026-12 |
| 1 · Judge | Pre-registered verdicts on each AI policy | Each policy passes or is killed by its own gate | P8 ~2026-12; E1 2027-05-10; sector momentum 2027-09-04; P7 ≥12 months after activation |
| 2 · Broker-paper | Same engine on the owner's own hardware against an IBKR paper account | 1–3 months of broker-paper fills reconciled to the simulator, slippage calibrated, zero unattributed orders | After a Stage 1 pass |
| 3 · Small live capital | Autonomous live trading, capped and staged | Live results track paper within tolerance at each capital step | After Stage 2 |
| 4 · Scale | More capital, more policies | Each addition repeats Stages 0–3 | Open |

Stages 2–3 need owner decisions and a separate execution-layer plan. Nothing in this page
authorises a broker connection, credentials, or real capital; `scope.md` still governs.

## Focus now (in order)

1. **Keep the evidence clean.** Scheduled producers green, no missed agent windows, no identity
   drift, no uncommitted work left on the host (the nightly `git pull` fails on a dirty tree).
   A broken producer beats every item below.
2. **Activate P7.** Backup-gated tri-arm schema and initializer, the recorded SGD/USD opening
   observation, then the tri-arm orchestrator and its single status panel. It is the cleanest
   test of "does the AI allocate better than the rule?"
3. **P8/P9 observability.** Persist hourly/four-hour freshness and paired prompt metrics in the
   status projection; alert on missed windows and model/prompt drift.
4. **First-fill lifecycle rehearsal.** After the first P8 fill, rehearse backup and restore across
   the whole order → fill → exit path.
5. **P13/P14 evidence collection.** TradingView is active as a research cross-check/history source
   with a resumable current-liquid daily archive; Alpaca remains dormant. Neither has execution-price
   authority, and the archive does not solve historical-universe survivorship.
6. **P2 league collapse.** Retire books that answer no open question (regime-gated twins that
   currently match their parents) to cut nightly noise and review load.
7. **Cost per decision.** Report tokens and data cost per decision next to excess return, so the
   economics are visible before any live-capital discussion.

## Expansion candidates (after Stage 1, each needs its own plan)

| Candidate | Why | Main risk |
|---|---|---|
| AI monthly allocator over broad ETFs | Low turnover, cheap, judgement where costs don't eat it (P7's AI-only arm) | May just track a static mix |
| AI veto on a proven rule | The rule carries the edge; the model removes obvious bad entries | Vetoes can cut winners |
| Filing / earnings reader on acceptance-timestamped SEC text | Honest point-in-time text input; LLMs read text well | PEAD is thin and crowded |
| Model tournament on identical inputs | Choose the decision-maker on evidence | Trial count and token cost |
| Research agent drafting charters for owner approval | Speeds idea → frozen test | Idea flood; cap at one open charter |

Parked: intraday execution authority (needs quote/trade data and queue modelling), new markets,
options (premium selling showed no after-cost edge).

## Stop rules

Stop building toward live capital, and keep the engine as a research and portfolio piece, if by
**2027-09** no AI policy has cleared its gate, if running costs exceed demonstrated excess return
at the capital the owner will deploy, or if work drifts back into governance for an edge that does
not exist for two review cycles (the 2026-09-18 failure mode).
