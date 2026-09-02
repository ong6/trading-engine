
# 🖥️ Trading Engine — Mock Execution & UI Tech Design

**Status: tech design finalized 2026-07-16 — open questions settled (§8). No code yet.** Companion to
[trading-engine-design.md](trading-engine-design.md) (data + screener spec — **§12 defines the
current scope**) and [the research](../../research/trading-engine/retail-algo-trading-direction.md).

**Scope (revised 2026-07-16):** the current build is a **fully local mock trading system** on the
devbox — internal fill simulator, paper league, local UI. **No broker API, no Telegram, no
credentials, nothing inbound; only public data in and public derived data out (git).** The
verified moomoo integration plan is preserved in **Appendix A** as the deferred live phase (M5),
gated on the paper league producing a sleeve that clears its pre-registered bar for ~6+ months.

## 0 · Settled decisions

| Decision | Value |
|---|---|
| Execution (current build) | **Internal fill simulator** — no external broker. Simulated next-open fills + configurable slippage/cost model |
| Portfolios | **Paper league** (spec §12.4): N auto-traded strategy portfolios + benchmarks + **one human-traded discretionary portfolio via the ticket UI** |
| Topology | Everything **local to the devbox**; UI reachable from the corp intranet (that's fine — no money, no secrets). No Tailscale, no auth complexity |
| Stack | **FastAPI** backend + **Next.js** frontend (unchanged) |
| Autonomy | Strategy portfolios trade **fully automatically** (they're evidence generators); the discretionary portfolio is **manual approval per ticket** (it trains the real process) |
| Notifications | **Local only**: UI badges + daily `data/reports/` + journal lines. Telegram deferred to M5 |
| Reference notional | S$50k (~US$39k) per portfolio, so league results read directly as "what this would have done with my capital" |
| Cadence | Weekly review + refinement loop (§6) — refine via review, one change at a time |
| Real money | **Deferred (M5)** — Appendix A. Nothing in the current build can place a real order, by construction |

## 1 · Architecture — one box, three loops

```
DEVBOX (company intranet; public data in, git out — zero secrets)
│
│  NIGHTLY LOOP (cron, post-US-close)
│    collect.py (full-universe EOD + intraday archive + snapshots)
│    → screen.py (template + RS over ~5k names, regime gate)
│    → league.py (fill simulator: execute all auto-portfolios at next-open policy)
│    → report.py (screens/<date>.md, league.md, _meta.json)
│    → sync.py (git commit + push data/)
│
│  IDLE LOOP (queue_runner: capped pool ≤24 workers, nice 19,
│             load/RAM/disk guards — spec §12.7)
│    backtest farm: walk-forward, sweeps, robustness (spec §12.3 protocol)
│    → results table + data/reports/experiments/
│
│  INTERACTIVE LOOP (systemd services)
│    server/ FastAPI :8000 ── reads store/market.duckdb + data/
│    ui/ Next.js :3000     ── dashboard, league, ticket flow (discretionary paper)
│
└── store/market.duckdb (gitignored, grows: prices, intraday, fundamentals,
    snapshots, mock portfolios/orders/fills, experiment results)
```

Repo layout (broker/ shrinks to a simulator; everything else as before):

```
trading-engine/
  engine/         collect.py screen.py universe.py sync.py lib/
  sim/            fills.py (fill model: next-open, slippage, costs)
                  portfolio.py (positions, cash, R accounting)
                  league.py (runs all auto-portfolios daily)
                  strategies/ (one module per league member, pre-registered configs)
  farm/           queue_runner.py, jobs/ (walk-forward, sweep, bootstrap), protocol.md
  server/         main.py routes/ risk.py sizing.py events.py
  ui/             Next.js app
  data/           screens/ reports/ eod/ universe.csv _meta.json   ← commits
  store/          market.duckdb                                    ← gitignored
```

## 2 · The fill simulator — honest by design

- **Policy:** signals computed on close of day t → fills at **day t+1 open**, with slippage =
  max(half-spread estimate, 5bp) + 10bp round-trip cost — deliberately *worse* than the
  backtests' assumptions, so league results are conservative.
- Partial-fill/liquidity guard: a mock order may not exceed 1% of the name's median dollar
  volume (matters once the universe includes smaller names).
- **No same-bar fills, ever** — the look-ahead rule from the research, enforced in one place.
- Every fill is recorded with the exact bar + model inputs, so slippage assumptions can be
  re-litigated later against real fills (M5).

## 3 · UI — same five pages, mock-first

Persistent header: **MOCK banner** (always — there is no live mode in this build), regime badge,
data freshness. Pages:

1. **Dashboard** — today's screen (full-universe, liquid-large slice first), regime, league
   summary strip.
2. **League** *(new, replaces "account")* — equity curves per portfolio, rolling expectancy vs
   each sleeve's pre-registered decayed bar, drawdown, kill-criterion status, trade counts.
3. **Candidate → Ticket** — unchanged flow (chart, template checks, pre-filled ticket, 1%-risk
   sizing, playbook + emotion fields, risk-gate checklist) — but submits to the **discretionary
   paper portfolio** via the simulator.
4. **Positions & Orders** — all portfolios, filterable; discretionary positions get
   distance-to-stop and unrealized R.
5. **Journal** — discretionary paper trades with R-multiples and on-plan flags; league events;
   review status.

## 4 · Risk gates — unchanged, and they apply to paper

`risk.py` enforces the full `rules.md` gate table (stop present, 1% sizing, playbook named,
R:R ≥ 2, ≤ 4R open risk, earnings window, regime gate, circuit breaker) on the **discretionary
portfolio** — paper is where the process gets trained, so the gates run for real. Auto-portfolios
get the structural gates only (sizing, regime variants as configured); their point is to test
strategies, not to practice discipline. Every submit → audit log.

## 5 · What replaced the safety model

There is no PAPER/LIVE toggle in this build — **there is no LIVE**. The simulator cannot reach a
broker; that's the safety model. The M5 appendix keeps the designed toggle (guarded LIVE flip,
one-click kill, 24h auto-revert) for when real execution returns on personal hardware.

## 6 · Weekly review & refinement loop (unchanged in spirit, now fully local)

Sunday cron: `/watchlist-scan` + `/trading-review` + the farm's walk-forward re-validation →
review report to `reviews/` + league report refresh. Refinement rules stand: changes only at
reviews, one at a time, logged in `lessons.md`, justified by walk-forward evidence not last
week's P&L; every sleeve keeps its pre-registered decayed expectation + kill criterion — breach
= kill first, redesign later. League portfolios that die stay visible in the league table
(tombstoned) — negative results are results.

## 7 · Build phases (mirrors spec §12.6)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **M0** | Scaffold + full-universe EOD collect (max history) + nightly cron | `_meta.json` shows a clean nightly run over ~4k+ names |
| **M1** | Full-universe screener + regime + point-in-time snapshots + sync | First `data/screens/<date>.md` pulled on the laptop |
| **M2** | Fill simulator + paper league + daily `league.md` | 5+ auto-portfolios trading daily, conservative fill model verified against §2 |
| **M3** | FastAPI + Next.js UI (local): dashboard, league, ticket flow | Discretionary paper trade end-to-end through risk gates |
| **M4** | Backtest farm + intraday/fundamentals mining | First pre-registered experiment report published; intraday archive accumulating |
| **M5** | *(deferred, gated)* real execution — Appendix A | A sleeve clears its bar ~6+ months in the league |

## 8 · Formerly-open questions — settled 2026-07-16

1. **League membership v1 (settled):** template-top5, template-top10-banded, dual-momentum,
   MR-overlay, regime-gated variants of each, EW + SPY benchmarks. Membership changes only at
   weekly reviews, one at a time.
2. **Intraday archive breadth (settled):** top-500 by dollar volume + watchlist names.
   Politeness caps per source; growth governed by the disk watchdog (engine spec §12.7).
3. **Intranet access to :3000/:8000 (settled as non-blocking):** SSH port-forward is the
   accepted baseline; direct intranet access is a convenience to verify during M3. Nothing
   depends on the answer.

---

## Appendix A · Deferred live phase (M5) — moomoo integration, verified 2026-07-15

Kept for the day a sleeve earns real money. All facts verified against official docs 2026-07-15:

- **Host:** a personal machine only (small SG VPS ~US$6–12/mo or home mini PC) — never company
  hardware: broker credentials on corp infra = policy + inspection risk, corp egress
  filtering/TLS interception already observed (Stooq blocked, pip MITM'd), and the kill switch
  must not depend on corp VPN access. UI via personal Tailscale.
- **moomoo OpenAPI is not REST:** everything goes through **OpenD**, a gateway daemon
  (Command Line flavor, official Ubuntu support; TCP 11111 localhost) consumed by the
  `moomoo-api` Python SDK (PyPI ≥10.8.6808; forced minimum-version upgrades happen).
- **First login per machine needs SMS** (`input_phone_verify_code` via OpenD console); steady
  state auto-relogin works with `login_pwd_md5`. One-time API Questionnaire in the app.
- **SG accounts:** US stocks/ETFs fully API-tradable (SGX is not); order types
  limit/market/stop/stop-limit/trailing, TIF DAY/GTC/GTD, sessions RTH/ETH/OVERNIGHT
  (overnight = limit only). `unlock_trade` needed for REAL only. Use the **new US paper backend**
  (legacy being phased out). Rate limits per 30s: place 15 · modify/cancel 20 · order_list 10 ·
  snapshot 60 · unlock 10; order/fill push via `TradeOrderHandlerBase`/`TradeDealHandlerBase` —
  consume pushes, never poll.
- **Data:** US real-time L1+depth currently free promotionally for SG (revocable); subscription
  quota 100–300 symbol-type pairs at this asset level.
- **Safety model (designed 2026-07-15):** in-UI PAPER↔LIVE toggle, asymmetric — LIVE requires
  typed `LIVE` + server-side `unlock_trade` + per-order typed-ticker confirmation, logged +
  notified, **auto-reverts to PAPER after 24h inactivity**; back to PAPER is one unguarded click
  ("Kill & cancel" option). Secrets in `.env` (chmod 600, gitignored), never in the repo, never
  returned by any endpoint.
- **Telegram** (send-only v1): fills, env switches, circuit breaker, stale data, OpenD-needs-SMS;
  v2 option = inline approve/reject via tailnet-only webhook.
- **Go-live gate:** league evidence (~6+ months over the bar) + ≥1 month reconciling simulator
  fills vs moomoo paper fills + first live month at minimum size measuring realized slippage
  vs the fill model.
